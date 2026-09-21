"""Leakage, temporal boundaries, train-only fitting and clustered uncertainty."""

import inspect
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score, matthews_corrcoef
from threadpoolctl import threadpool_limits

from dataset_pk99.inactivity_features import FEATURES, build_features, make_dataset
from dataset_pk99.inactivity_evaluation import (
    MetricEvaluator, choose_threshold, cluster_weights, clustered_bootstrap,
    model_matrix, select_models, temporal_split,
)
from dataset_pk99.predict_inactivity import save_csv


def fixture():
    accounts = pd.DataFrame({"account_id": [1, 2, 3], "opened_at": pd.to_datetime(["1997-01-01", "1997-01-01", "1997-04-01"])})
    rows = [(1, "1997-01-01", "", 10), (1, "1997-04-01", "", 20),
            (1, "1997-05-01", "UROK", 30), (1, "1997-05-02", "", 40),
            (2, "1997-01-01", "", 10), (2, "1997-04-01", "", 20),
            (2, "1997-05-02", "", 40)]
    trans = pd.DataFrame(rows, columns=["account_id", "trans_date", "k_symbol", "amount"])
    trans["trans_date"] = pd.to_datetime(trans.trans_date)
    trans["trans_id"] = np.arange(len(trans))
    trans["type"] = "PRIJEM"
    trans["balance"] = trans.amount * 10
    return accounts, trans


def features_at(dates, trans=None, scope="all_transactions"):
    accounts, original = fixture()
    return build_features(accounts, original if trans is None else trans, pd.DatetimeIndex(dates),
                          pd.Timestamp("1997-01-01"), scope)


def model_data():
    rng = np.random.default_rng(47)
    n = 240
    frame = pd.DataFrame({name: rng.uniform(0, 10, n) for name in FEATURES})
    frame["account_id"] = np.arange(n) % 30
    frame["snapshot_date"] = np.repeat(pd.date_range("1995-01-31", periods=24, freq="ME"), 10)
    frame["label_end"] = frame.snapshot_date + pd.Timedelta(days=30)
    frame["y"] = ((frame.recency_days > 7) | (np.arange(n) % 13 == 0)).astype(int)
    return frame


class FeatureTests(unittest.TestCase):
    def test_future_append_modify_remove_does_not_change_features(self):
        _, trans = fixture()
        expected = features_at(["1997-04-01"])
        past = trans.loc[trans.trans_date.le("1997-04-01")]
        assert_frame_equal(expected, features_at(["1997-04-01"], past))
        altered = trans.copy()
        altered.loc[altered.trans_date.gt("1997-04-01"), ["amount", "balance"]] = 10**8
        added = altered.iloc[[0]].assign(trans_id=999, trans_date=pd.Timestamp("1997-12-31"), amount=10**9)
        assert_frame_equal(expected, features_at(["1997-04-01"], pd.concat([altered, added])))

    def test_feature_values_and_closed_past_open_window_start(self):
        f = features_at(["1997-04-01"]).set_index("account_id")
        self.assertEqual(f.loc[1, "transactions_to_T"], 2)
        self.assertEqual(f.loc[1, "count_90d"], 1)  # Jan 1 = T-90 excluded
        self.assertEqual(f.loc[1, "amount_sum_90d"], 20)
        self.assertEqual(f.loc[1, "inflow_90d"], 20)
        self.assertEqual(f.loc[1, "outflow_90d"], 0)
        self.assertEqual(f.loc[1, "last_balance"], 200)
        self.assertEqual(f.loc[1, "gap_mean_days"], 90)
        self.assertEqual(f.loc[3, "transactions_to_T"], 0)
        self.assertTrue(np.isnan(f.loc[3, "last_balance"]))

    def test_target_boundaries_scope_history_and_censoring(self):
        _, trans = fixture()
        f = features_at(["1997-04-01", "1997-05-02", "1997-05-03"])
        d, audit = make_dataset(f, trans, "all_transactions", 30, pd.Timestamp("1997-06-01"), 90)
        first = d.loc[d.snapshot_date.eq("1997-04-01")].set_index("account_id")
        self.assertEqual(first.loc[1, "y"], 0)  # T+H included
        self.assertEqual(first.loc[2, "y"], 1)  # T excluded; T+H+1 excluded
        self.assertNotIn(3, d.account_id.unique())
        self.assertTrue(d.snapshot_date.le("1997-05-02").all())
        self.assertEqual(audit["removed_history"], 3)
        self.assertEqual(audit["removed_right_censoring"], 2)
        f = features_at(["1997-04-01"], scope="excluding_routine")
        d, _ = make_dataset(f, trans, "excluding_routine", 30, pd.Timestamp("1997-06-01"), 90)
        self.assertEqual(d.y.tolist(), [1, 1])
        d, _ = make_dataset(f, trans, "excluding_routine", 30, pd.Timestamp("1997-06-01"), 91)
        self.assertTrue(d.empty)

    def test_labels_ignore_events_outside_future_interval(self):
        _, trans = fixture()
        f = features_at(["1997-04-01"])
        expected, _ = make_dataset(f, trans, "all_transactions", 30, pd.Timestamp("1997-06-01"), 90)
        changed = trans.loc[trans.trans_date.gt("1997-04-01") & trans.trans_date.le("1997-05-01")]
        actual, _ = make_dataset(f, changed, "all_transactions", 30, pd.Timestamp("1997-06-01"), 90)
        assert_frame_equal(expected, actual)

    def test_observable_history_uses_global_start_not_old_opening(self):
        accounts, trans = fixture()
        accounts["opened_at"] = pd.Timestamp("1990-01-01")
        f = build_features(accounts, trans, pd.DatetimeIndex(["1997-04-01"]), pd.Timestamp("1997-01-01"), "all_transactions")
        self.assertTrue(f.observed_history_days.eq(90).all())
        self.assertTrue(f.account_age_days.gt(2000).all())


class EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.limits = threadpool_limits(limits=2)
        cls.limits.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.limits.__exit__(None, None, None)

    def test_purge_is_strict_for_every_horizon(self):
        for horizon in (90, 120, 180):
            frame = model_data()
            frame["label_end"] = frame.snapshot_date + pd.Timedelta(days=horizon)
            splits, definitions, purge = temporal_split(frame, "1996-01-01", "1996-09-01")
            self.assertTrue((splits["train"].label_end < pd.Timestamp("1996-01-01")).all())
            self.assertTrue((splits["validation"].label_end < pd.Timestamp("1996-09-01")).all())
            self.assertTrue(splits["test"].snapshot_date.ge("1996-09-01").all())
            self.assertGreater(sum(row["snapshots"] for row in purge), 0)
            self.assertEqual(len(definitions), 3)
        # Equality also purged: no target event on the next period's first day.
        frame.loc[0, "label_end"] = pd.Timestamp("1996-01-01")
        splits, _, _ = temporal_split(frame, "1996-01-01", "1996-09-01")
        self.assertNotIn(0, splits["train"].index)

    def test_model_whitelist_and_train_only_preprocessing(self):
        frame = model_data()
        train, val = frame.iloc[:100].copy(), frame.iloc[100:160].copy()
        train.loc[0, "amount_mean_30d"] = np.nan
        val["account_age_days"] = 1000000.
        models, _, _ = select_models(train, val, 7)
        matrix = model_matrix(train, "logistic")
        self.assertNotIn("account_id", matrix)
        self.assertNotIn("y", matrix)
        self.assertNotIn("label_end", matrix)
        fitted = models["logistic"].estimator
        np.testing.assert_allclose(fitted[0].statistics_, matrix.median().to_numpy())
        np.testing.assert_allclose(fitted[1].mean_, fitted[0].transform(matrix).mean(axis=0))
        self.assertLess(fitted[1].mean_[0], 10.)
        self.assertFalse(models["hist_gradient_boosting"].estimator.early_stopping)

    def test_test_cannot_change_selection_and_seed_reproduces_predictions(self):
        frame = model_data()
        first, winner1, search1 = select_models(frame.iloc[:100], frame.iloc[100:160], 8)
        frame.loc[160:, "y"] = 1-frame.loc[160:, "y"]
        frame.loc[160:, list(FEATURES)] = 100000.
        second, winner2, search2 = select_models(frame.iloc[:100], frame.iloc[100:160], 8)
        self.assertNotIn("test", inspect.signature(select_models).parameters)
        self.assertEqual(winner1, winner2)
        self.assertEqual(search1, search2)
        for name in first:
            self.assertEqual(first[name].threshold, second[name].threshold)
            np.testing.assert_array_equal(first[name].predict(frame.iloc[160:]), second[name].predict(frame.iloc[160:]))

    def test_validation_can_choose_threshold_and_model_params(self):
        self.assertEqual(choose_threshold([0, 0, 1], [.1, .5, .9]), .9)
        self.assertEqual(choose_threshold([1, 0, 0], [.1, .5, .9]), .1)
        frame = model_data()
        models, winner, candidates = select_models(frame.iloc[:100], frame.iloc[100:160], 9)
        for name, model in models.items():
            best = max([c for c in candidates if c["model"] == name],
                       key=lambda c: (c["average_precision"], -c["brier"], -c["candidate"]))
            self.assertEqual(model.params, best["params"])
            self.assertEqual(model.threshold, best["threshold"])
        self.assertEqual(models[winner].validation_metrics["average_precision"],
                         max(m.validation_metrics["average_precision"] for m in models.values()))

    def test_weighted_metrics_match_sklearn_including_ties(self):
        y = np.array([0, 1, 1, 0, 0, 1])
        p = np.array([.1, .1, .7, .7, .2, .9])
        w = np.array([2, 2, 1, 0, 3, 3])
        result = MetricEvaluator(y, p, .5).compute(w)
        self.assertAlmostEqual(result["average_precision"], average_precision_score(y, p, sample_weight=w))
        self.assertAlmostEqual(result["roc_auc"], roc_auc_score(y, p, sample_weight=w))
        self.assertAlmostEqual(result["brier"], brier_score_loss(y, p, sample_weight=w))
        self.assertAlmostEqual(result["mcc"], matthews_corrcoef(y, p >= .5, sample_weight=w))
        idx = np.repeat(np.arange(len(y)), w)
        self.assertAlmostEqual(result["average_precision"], average_precision_score(y[idx], p[idx]))

    def test_bootstrap_keeps_cluster_rows_together_and_is_reproducible(self):
        ids = np.array([1, 1, 2, 2, 3, 3])
        weights = cluster_weights(ids, np.random.default_rng(17))
        np.testing.assert_array_equal(weights[::2], weights[1::2])
        self.assertEqual(weights[::2].sum(), 3)
        frame = pd.DataFrame({"account_id": ids, "y": [0, 1, 0, 0, 1, 1]})
        p = np.array([.1, .3, .2, .1, .7, .9])
        ci1, draws1 = clustered_bootstrap(frame, p, .5, 30, 77)
        ci2, draws2 = clustered_bootstrap(frame, p, .5, 30, 77)
        assert_frame_equal(draws1, draws2)
        assert_frame_equal(pd.DataFrame(ci1), pd.DataFrame(ci2))

    def test_single_class_training_is_explicit_fallback(self):
        frame = model_data()
        train = frame.iloc[:100].assign(y=0)
        models, _, _ = select_models(train, frame.iloc[100:160], 4)
        self.assertTrue(all(m.fallback for m in models.values()))
        self.assertTrue(all(np.all(m.predict(frame.iloc[160:]) == 0) for m in models.values()))

    def test_test_summary_can_be_deferred_until_freeze(self):
        _, definitions, _ = temporal_split(model_data(), "1996-01-01", "1996-09-01", summarize_test=False)
        self.assertNotIn("positives", definitions[-1])
        self.assertIn("positives", definitions[0])

    def test_nine_month_validation_remains_nonempty_after_180_day_purge(self):
        frame = model_data()
        frame["label_end"] = frame.snapshot_date + pd.Timedelta(days=180)
        splits, _, _ = temporal_split(frame, "1995-10-01", "1996-07-01")
        self.assertFalse(splits["validation"].empty)

    def test_feature_csv_round_trip_preserves_tree_predictions(self):
        frame = model_data()
        models, _, _ = select_models(frame.iloc[:100], frame.iloc[100:160], 7)
        test = frame.iloc[160:][list(FEATURES)].reset_index(drop=True)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "features.csv.gz"
            save_csv(test, path)
            restored = pd.read_csv(path, float_precision="round_trip")
        assert_frame_equal(test, restored, check_exact=True)
        for model in models.values():
            np.testing.assert_array_equal(model.predict(test), model.predict(restored))


if __name__ == "__main__":
    unittest.main()
