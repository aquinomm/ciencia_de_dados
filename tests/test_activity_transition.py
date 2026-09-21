"""Prospective eligibility, silence-episode deduplication and selection isolation."""

import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal
from threadpoolctl import threadpool_limits

from dataset_pk99.activity_transition import (
    assert_active, audit_split_integrity, build_active_dataset, episode_census,
    episode_summary, episode_tables, select_active_models,
)
from dataset_pk99.inactivity_features import FEATURES, build_features
from dataset_pk99.inactivity_evaluation import model_matrix, temporal_split
from dataset_pk99.predict_activity_transition import Config, require_branch
from test_inactivity_prediction import model_data


def fixture():
    accounts = pd.DataFrame({"account_id": [1, 2], "opened_at": pd.to_datetime(["1996-01-01"]*2)})
    trans = pd.DataFrame({"account_id": [1, 1, 1, 2, 2, 2],
                          "trans_date": pd.to_datetime(["1996-01-01", "1996-12-31", "1997-06-01",
                                                        "1996-01-01", "1997-01-01", "1997-03-31"]),
                          "type": ["PRIJEM"]*6, "k_symbol": [""]*6,
                          "amount": [100.]*6, "balance": [1000.]*6, "trans_id": range(6)})
    return accounts, trans


def cohort(dates, active_days=30, horizon=90, end="1997-12-31", transactions=None):
    accounts, original = fixture()
    trans = original if transactions is None else transactions
    dates = pd.DatetimeIndex(dates)
    f = build_features(accounts, trans, dates, pd.Timestamp("1996-01-01"), "all_transactions")
    return build_active_dataset(f, trans, "all_transactions", horizon, pd.Timestamp(end), active_days, 180)


class CohortTests(unittest.TestCase):
    def test_active_cutoff_is_inclusive_and_applied_before_target_builder(self):
        accounts, trans = fixture()
        f = build_features(accounts, trans, pd.DatetimeIndex(["1997-01-30", "1997-01-31"]),
                           pd.Timestamp("1996-01-01"), "all_transactions")
        from dataset_pk99.inactivity_features import make_dataset
        with patch("dataset_pk99.activity_transition.make_dataset", wraps=make_dataset) as spy:
            d, audit = build_active_dataset(f, trans, "all_transactions", 90, pd.Timestamp("1997-12-31"), 30)
        self.assertTrue(spy.call_args.args[0].recency_days.le(30).all())
        self.assertIn(30, d.recency_days.values)
        self.assertNotIn(31, d.recency_days.values)
        self.assertEqual(audit["removed_inactive_at_T"], 1)

    def test_same_silence_gap_is_one_episode_not_two_events(self):
        d, _ = cohort(["1996-12-31", "1997-01-30"])
        pos = d.loc[d.account_id.eq(1)]
        self.assertEqual(pos.y.tolist(), [1, 1])
        summary = episode_summary(pos)
        self.assertEqual(summary["positives"], 2)
        self.assertEqual(summary["positive_episodes"], 1)
        self.assertEqual(summary["positive_accounts"], 1)
        self.assertEqual(summary["fraction_snapshots_beyond_first_per_episode"], .5)
        self.assertEqual(summary["fraction_positives_from_repeated_accounts"], 1.)
        events, monthly, cross = episode_tables(pos, "test")
        self.assertEqual(events.positive_snapshots.tolist(), [2])
        self.assertEqual(cross.positive_episodes.sum(), 1)
        self.assertEqual(sum(row["positive_episodes"] for row in monthly), 2)  # represented twice, not new twice

    def test_reactivation_then_new_silence_is_a_different_episode(self):
        d, _ = cohort(["1996-12-31", "1997-06-01"])
        pos = d.loc[d.account_id.eq(1)]
        self.assertEqual(episode_summary(pos)["positive_episodes"], 2)
        self.assertEqual(episode_summary(pos)["positive_accounts"], 1)

    def test_future_edit_cannot_change_eligibility_or_features(self):
        _, trans = fixture()
        original, _ = cohort(["1997-01-30"])
        past = trans.loc[trans.trans_date.le("1997-01-30")]
        changed, _ = cohort(["1997-01-30"], transactions=past)
        cols = ["account_id", "snapshot_date", *FEATURES, "last_activity_at_T"]
        assert_frame_equal(original[cols], changed[cols])

    def test_target_end_inclusive_and_activity_at_T_is_past(self):
        d, _ = cohort(["1997-01-01"], horizon=89)
        # Account 2 activity on T qualifies the account; Mar 31 = T+89 makes it negative.
        self.assertEqual(d.set_index("account_id").loc[2, "y"], 0)
        d, _ = cohort(["1997-01-01"], horizon=88)
        self.assertEqual(d.set_index("account_id").loc[2, "y"], 1)

    def test_right_censoring_and_minimum_history_are_not_labels(self):
        d, audit = cohort(["1996-01-01", "1997-06-01"], end="1997-07-01")
        self.assertTrue(d.empty)
        self.assertEqual(audit["removed_history"], 2)
        self.assertGreater(audit["removed_right_censoring"], 0)

    def test_census_matches_calendar_and_reports_unsampled_gaps(self):
        accounts, trans = fixture()
        dates = pd.DatetimeIndex(["1996-12-31", "1997-01-30"])
        d, _ = cohort(dates)
        census = episode_census(accounts, trans, dates, "all_transactions", 90, 30, 180,
                                pd.Timestamp("1996-01-01"), pd.Timestamp("1997-12-31"))
        captured = census.loc[census.captured_by_calendar]
        self.assertEqual(set(captured.episode_id), set(d.loc[d.y.eq(1), "episode_id"]))
        self.assertEqual(captured.calendar_positive_snapshots.sum(), d.y.sum())
        self.assertTrue((~census.captured_by_calendar).any())

    def test_no_history_no_events_returns_empty_census(self):
        accounts, trans = fixture()
        census = episode_census(accounts, trans, pd.DatetimeIndex(["1996-01-01"]), "all_transactions", 90,
                                30, 10000, pd.Timestamp("1996-01-01"), pd.Timestamp("1997-12-31"))
        self.assertTrue(census.empty)


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.limits = threadpool_limits(limits=2)
        cls.limits.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.limits.__exit__(None, None, None)

    def test_frequency_baseline_has_only_one_past_feature(self):
        frame = model_data()
        frame["episode_id"] = "future-derived-metadata"
        self.assertEqual(list(model_matrix(frame, "frequency")), ["count_30d"])
        self.assertNotIn("episode_id", model_matrix(frame, "logistic"))
        self.assertNotIn("account_id", model_matrix(frame, "hist_gradient_boosting"))

    def test_training_general_population_is_rejected(self):
        frame = model_data()
        frame.loc[0, "recency_days"] = 31
        with self.assertRaisesRegex(ValueError, "active population"):
            select_active_models(frame.iloc[:100], frame.iloc[100:160], 30, 42)

    def test_all_estimators_fit_only_eligible_train_and_validation_controls_threshold(self):
        frame = model_data()
        train, val = frame.iloc[:100], frame.iloc[100:160].copy()
        val["account_age_days"] = 100000.
        models, _, _ = select_active_models(train, val, 30, 42)
        self.assertEqual(set(models), {"prevalence", "recency", "frequency", "logistic", "hist_gradient_boosting"})
        np.testing.assert_allclose(models["logistic"].estimator[0].statistics_, train[list(FEATURES)].median())
        self.assertLess(models["logistic"].estimator[1].mean_[0], 10.)
        self.assertEqual(list(models["frequency"].estimator.feature_names_in_), ["count_30d"])

    def test_no_positive_train_does_not_masquerade_as_fitted_models(self):
        frame = model_data()
        models, winner, _ = select_active_models(frame.iloc[:100].assign(y=0), frame.iloc[100:160], 30, 42)
        self.assertEqual(list(models), ["prevalence"])
        self.assertEqual(winner, "prevalence")

    def test_no_validation_events_is_explicit_prior_selection(self):
        frame = model_data()
        models, winner, _ = select_active_models(frame.iloc[:100], frame.iloc[100:160].assign(y=0), 30, 42)
        self.assertEqual(winner, "prevalence")
        self.assertTrue(all(model.threshold > 1 for model in models.values()))

    def test_reproducibility_and_test_not_used_for_selection(self):
        frame = model_data()
        a, wa, ca = select_active_models(frame.iloc[:100], frame.iloc[100:160], 30, 42)
        frame.loc[160:, "y"] = 1-frame.loc[160:, "y"]
        b, wb, cb = select_active_models(frame.iloc[:100], frame.iloc[100:160], 30, 42)
        self.assertEqual(wa, wb)
        self.assertEqual(ca, cb)
        for name in a:
            self.assertEqual(a[name].threshold, b[name].threshold)
            np.testing.assert_array_equal(a[name].predict(frame.iloc[160:]), b[name].predict(frame.iloc[160:]))

    def test_default_protocol_is_new_and_does_not_rescue_single_class_train(self):
        config = Config()
        self.assertEqual(config.validation_start, "1997-01-01")
        self.assertEqual(config.active_windows, (30, 15, 60))
        self.assertEqual(config.horizons, (90, 120, 180))

    def test_branch_guard_never_switches_branch(self):
        with patch("dataset_pk99.predict_activity_transition.subprocess.check_output", return_value="main\n") as command:
            with self.assertRaisesRegex(RuntimeError, "berka-temporal"):
                require_branch()
        self.assertEqual(command.call_count, 1)
        self.assertEqual(command.call_args.args[0], ["git", "branch", "--show-current"])

    def test_split_audit_rejects_reused_episode_across_splits(self):
        frame = model_data()
        frame["episode_id"] = np.where(frame.y.eq(1), frame.index.astype(str), "")
        splits, _, _ = temporal_split(frame, "1996-01-01", "1996-09-01")
        self.assertTrue(audit_split_integrity(splits, 30, "1996-01-01", "1996-09-01")["positive_episodes_disjoint"])
        for part in (splits["train"], splits["test"]):
            part.loc[part.y.eq(1), "episode_id"] = "shared-gap"
        with self.assertRaisesRegex(AssertionError, "episode crosses"):
            audit_split_integrity(splits, 30, "1996-01-01", "1996-09-01")


if __name__ == "__main__":
    unittest.main()
