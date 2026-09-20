"""Boundary, censoring and leakage checks on small, hand-verifiable histories."""

import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from dataset_pk99.eda import (
    Config, account_behavior, build_snapshots, eligible_mask,
    evaluate_targets, snapshot_calendar, summarize_gaps, validate_tables,
)


def fixture():
    rows = [(1, "1997-01-01"), (1, "1997-04-01"), (1, "1997-04-01"),
            (1, "1997-05-01"), (1, "1997-06-01"),
            (2, "1997-01-01"), (2, "1997-04-01"), (2, "1997-05-02"),
            (2, "1997-12-31")]
    transactions = pd.DataFrame(rows, columns=["account_id", "trans_date"])
    transactions["trans_id"] = range(len(rows))
    for column in ("type", "operation", "k_symbol"):
        transactions[column] = ""
    return {
        "accounts": pd.DataFrame({"account_id": [1, 2, 3, 4],
                                  "opened_at": ["1997-01-01"] * 3 + ["1997-04-20"]}),
        "owners": pd.DataFrame({"account_id": [1, 2, 4], "client_id": [11, 12, 14]}),
        "transactions": transactions,
    }


class TemporalTests(unittest.TestCase):
    def setUp(self):
        self.accounts, self.transactions, _ = validate_tables(fixture())
        self.start, self.end = pd.Timestamp("1997-01-01"), pd.Timestamp("1997-12-31")
        self.config = Config(history_days=(60,), horizons=(30,), thresholds=(30,),
                             min_transactions=(2,), reactivation_days=60)

    def snapshots(self, dates, transactions=None):
        return build_snapshots(self.accounts, self.transactions if transactions is None else transactions,
                               pd.DatetimeIndex(dates), self.start, self.end, self.config)

    def test_target_boundaries_and_incomplete_horizon(self):
        features, labels = self.snapshots(["1997-04-01", "1997-12-01", "1997-12-02"])
        april = labels.loc[labels.snapshot_date.eq("1997-04-01")].set_index("account_id")
        self.assertEqual(april.loc[1, "future_transaction_count"], 1)  # T+H included
        self.assertEqual(april.loc[1, "future_inactivity_flag"], 0)
        self.assertEqual(april.loc[2, "future_inactivity_flag"], 1)  # T+H+1 excluded
        self.assertNotIn(4, april.index)  # not yet open at T
        self.assertTrue(labels.snapshot_date.le("1997-12-01").all())
        row = features.loc[features.account_id.eq(1) & features.snapshot_date.eq("1997-04-01")].iloc[0]
        self.assertEqual(row.transactions_to_T, 3)  # both transactions on T are history

    def test_future_changes_cannot_change_features(self):
        original, _ = self.snapshots(["1997-04-01"])
        changed = self.transactions.loc[self.transactions.trans_date.le("1997-04-01")].copy()
        without_future, _ = self.snapshots(["1997-04-01"], changed)
        assert_frame_equal(original, without_future)

    def test_no_history_and_minimum_history_excluded(self):
        features, labels = self.snapshots(["1997-04-01"])
        mask = eligible_mask(features, 60, 2, self.config)
        self.assertEqual(set(features.loc[mask, "account_id"]), {1, 2})
        self.assertFalse(eligible_mask(features, 91, 2, self.config).any())
        summary, _, eligibility = evaluate_targets(features, labels, self.end, self.config)
        row = summary.loc[summary.calendar.eq("all_complete")].iloc[0]
        self.assertEqual((row.observations, row.positives, row.positive_accounts), (2, 1, 1))
        self.assertEqual(row.prevalence, .5)
        self.assertEqual(row.positive_fixed_followup_returns, 1)
        self.assertEqual(eligibility.iloc[0].eligible, 2)

    def test_history_is_truncated_at_global_start(self):
        self.accounts["opened_at"] = pd.Timestamp("1990-01-01")
        features, _ = self.snapshots(["1997-04-01"])
        self.assertTrue(features.observed_history_days.eq(90).all())

    def test_same_day_transactions_and_missing_accounts(self):
        metrics, episodes, _ = account_behavior(self.accounts, self.transactions, self.start, self.end)
        self.assertEqual(metrics.set_index("account_id").loc[1, "transaction_count"], 5)
        self.assertEqual(metrics.set_index("account_id").loc[3, "transaction_count"], 0)
        self.assertTrue(episodes.loc[~episodes.right_censored, "gap_days"].gt(0).all())
        self.assertEqual(episodes.right_censored.sum(), 2)

    def test_long_gaps_include_censored_and_fixed_followup(self):
        episodes = pd.DataFrame({
            "account_id": [1, 2, 3, 4],
            "gap_start": pd.to_datetime(["1997-01-01", "1997-01-01", "1997-08-01", "1997-01-01"]),
            "next_transaction": pd.to_datetime(["1997-04-02", None, "1997-12-01", "1997-04-01"]),
            "gap_days": [91, 364, 122, 90], "right_censored": [False, True, False, False],
        })
        summary, counts = summarize_gaps(episodes, (90, 400), self.end, 180)
        row = summary.iloc[0]
        self.assertEqual((row.episodes, row.completed_episodes, row.right_censored_episodes), (3, 2, 1))
        self.assertAlmostEqual(row.account_observed_return_fraction, 2 / 3)
        self.assertEqual((row.fixed_followup_episodes, row.fixed_followup_returns), (2, 1))
        self.assertEqual(row.fixed_followup_return_fraction, .5)
        self.assertTrue(pd.isna(summary.iloc[1].episode_observed_return_fraction))
        self.assertEqual(counts.episodes.sum(), 3)

    def test_duplicate_owner_and_impossible_dates_rejected(self):
        data = fixture()
        data["owners"] = pd.concat([data["owners"], data["owners"].iloc[[0]]])
        with self.assertRaisesRegex(ValueError, "duplicada"):
            validate_tables(data)
        data = fixture()
        data["transactions"].loc[0, "trans_date"] = "1996-12-31"
        with self.assertRaisesRegex(ValueError, "anteriores"):
            validate_tables(data)

    def test_empty_eligible_cohort_is_not_reported_as_zero_prevalence(self):
        features, labels = self.snapshots(["1997-12-31"])
        summary, _, _ = evaluate_targets(features, labels, self.end, self.config)
        self.assertTrue(summary.observations.eq(0).all())
        self.assertTrue(summary.prevalence.isna().all())

    def test_explicit_calendar_is_deduplicated_and_validated(self):
        config = Config(snapshot_dates=("1997-04-01", "1997-04-01"))
        self.assertEqual(len(snapshot_calendar(config, self.start, self.end)), 1)
        with self.assertRaises(ValueError):
            snapshot_calendar(Config(snapshot_dates=("1998-01-01",)), self.start, self.end)

    def test_common_calendar_preserves_cohort_across_horizons(self):
        self.config = Config(history_days=(60,), horizons=(30, 60), min_transactions=(2,))
        features, labels = self.snapshots(["1997-04-01", "1997-11-30"])
        summary, _, _ = evaluate_targets(features, labels, self.end, self.config)
        common = summary.loc[summary.calendar.eq("common_calendar")]
        self.assertEqual(common.observations.tolist(), [2, 2])
        all_complete = summary.loc[summary.calendar.eq("all_complete")]
        self.assertEqual(all_complete.observations.tolist(), [4, 2])

    def test_recency_filter_depends_only_on_past_activity(self):
        features, labels = self.snapshots(["1997-04-01", "1997-07-31"])
        recent = Config(history_days=(60,), horizons=(30,), min_transactions=(2,), max_recency_days=30)
        summary, _, _ = evaluate_targets(features, labels, self.end, recent)
        row = summary.loc[summary.calendar.eq("all_complete")].iloc[0]
        self.assertEqual((row.observations, row.positives), (2, 1))

    def test_scope_without_activity_preserves_accounts_but_has_no_episodes(self):
        metrics, episodes, _ = account_behavior(self.accounts, self.transactions.iloc[:0], self.start, self.end)
        self.assertTrue(metrics.transaction_count.eq(0).all())
        self.assertTrue(episodes.empty)


if __name__ == "__main__":
    unittest.main()
