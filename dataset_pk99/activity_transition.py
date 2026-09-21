"""Prospective active-account cohorts and deduplicated silence-episode audits."""

import numpy as np
import pandas as pd

from .inactivity_features import FEATURES, make_dataset, activity_subset
from .inactivity_evaluation import select_models, summarize

MODELS = ("prevalence", "recency", "frequency", "logistic", "hist_gradient_boosting")
BASELINES = ("prevalence", "recency", "frequency")


def assert_active(frame, active_days):
    if frame.empty or not frame.recency_days.between(0, active_days, inclusive="both").all():
        raise ValueError("All model rows must belong to the prespecified active population")


def build_active_dataset(features, transactions, scope, horizon, observation_end,
                         active_days=30, history_days=180):
    """Filter using past-only eligibility BEFORE computing any future labels."""
    if not 0 < active_days < horizon or history_days < 1:
        raise ValueError("Require 0 < active_days < horizon and positive history")
    history = features.observed_history_days.ge(history_days)
    known_activity = features.transactions_to_T.ge(1)
    active = features.recency_days.between(0, active_days, inclusive="both")
    eligible = features.loc[history & known_activity & active].copy()
    frame, previous = make_dataset(eligible, transactions, scope, horizon, observation_end, history_days, 1)
    audit = {"candidates_after_opening": len(features), "removed_history": int((~history).sum()),
             "removed_no_activity": int((history & ~known_activity).sum()),
             "removed_inactive_at_T": int((history & known_activity & ~active).sum()),
             "active_before_censoring": len(eligible),
             "removed_right_censoring": previous["removed_right_censoring"],
             "eligible_snapshots": len(frame), "eligible_accounts": frame.account_id.nunique()}
    frame["last_activity_at_T"] = frame.snapshot_date - pd.to_timedelta(frame.recency_days, unit="D")
    # Same account + same last active day means the same uninterrupted silence gap.
    episode = frame.account_id.astype(str) + ":" + frame.last_activity_at_T.dt.strftime("%Y-%m-%d")
    frame["episode_id"] = episode.where(frame.y.eq(1), "")
    frame["silence_H_day"] = (frame.last_activity_at_T + pd.Timedelta(days=horizon)).where(frame.y.eq(1))
    if len(frame):
        assert_active(frame, active_days)
        positive = frame.loc[frame.y.eq(1)]
        assert (positive.silence_H_day > positive.snapshot_date).all()
        assert (positive.silence_H_day <= positive.label_end).all()
    return frame, audit


def episode_summary(frame):
    positives = frame.loc[frame.y.eq(1)]
    by_account = positives.groupby("account_id").size()
    n = len(positives)
    episodes = positives.episode_id.nunique()
    return {**summarize(frame), "positive_episodes": episodes,
            "positive_accounts_with_multiple_snapshots": int(by_account.gt(1).sum()),
            "fraction_positives_from_repeated_accounts": float(by_account.loc[by_account.gt(1)].sum()/n) if n else np.nan,
            "fraction_snapshots_beyond_first_per_account": (n-len(by_account))/n if n else np.nan,
            "fraction_snapshots_beyond_first_per_episode": (n-episodes)/n if n else np.nan,
            "max_positive_snapshots_per_account": int(by_account.max()) if n else 0}


def episode_census(accounts, transactions, dates, scope, horizon, active_days, history_days,
                   observation_start, observation_end):
    """Descriptive census of feasible positive gaps, including gaps missed by the calendar."""
    opened = accounts.set_index("account_id").opened_at
    records = []
    for account, group in activity_subset(transactions, scope).groupby("account_id"):
        days = pd.DatetimeIndex(group.trans_date.unique()).sort_values()
        history_start = max(opened.loc[account], observation_start) + pd.Timedelta(days=history_days)
        next_days = days[1:].append(pd.DatetimeIndex([observation_end + pd.Timedelta(days=1)]))
        long_gap = (next_days - days).days > horizon
        for last, next_day in zip(days[long_gap], next_days[long_gap]):
            earliest = max(last, history_start)
            latest = min(last + pd.Timedelta(days=active_days),
                         next_day - pd.Timedelta(days=horizon + 1),
                         observation_end - pd.Timedelta(days=horizon))
            if earliest > latest:
                continue
            count = dates.searchsorted(latest, side="right") - dates.searchsorted(earliest, side="left")
            records.append({"episode_id": f"{account}:{last.date()}", "account_id": account,
                            "last_activity": last, "silence_H_day": last + pd.Timedelta(days=horizon),
                            "first_feasible_T": earliest, "last_feasible_T": latest,
                            "calendar_positive_snapshots": int(count), "captured_by_calendar": count > 0})
    return pd.DataFrame(records, columns=["episode_id", "account_id", "last_activity", "silence_H_day",
                                         "first_feasible_T", "last_feasible_T", "calendar_positive_snapshots",
                                         "captured_by_calendar"])


def episode_tables(frame, split):
    positive = frame.loc[frame.y.eq(1)]
    episodes = positive.groupby(["episode_id", "account_id", "last_activity_at_T", "silence_H_day"], as_index=False).agg(
        positive_snapshots=("y", "size"), first_snapshot=("snapshot_date", "min"),
        last_snapshot=("snapshot_date", "max"), latest_label_end=("label_end", "max"))
    episodes["split"] = split
    monthly = []
    for period, part in frame.groupby(frame.snapshot_date.dt.to_period("M")):
        monthly.append({"split": split, "snapshot_month": str(period), **episode_summary(part)})
    crossings = episodes.assign(event_month=episodes.silence_H_day.dt.to_period("M").astype(str)).groupby(
        "event_month", as_index=False).agg(positive_episodes=("episode_id", "nunique"),
                                          positive_accounts=("account_id", "nunique"))
    crossings["split"] = split
    return episodes, monthly, crossings


def audit_split_integrity(splits, active_days, validation_start, test_start):
    for frame in splits.values():
        assert_active(frame, active_days)
    assert (splits["train"].label_end < pd.Timestamp(validation_start)).all()
    assert (splits["validation"].label_end < pd.Timestamp(test_start)).all()
    episode_sets = {name: set(frame.loc[frame.y.eq(1), "episode_id"]) for name, frame in splits.items()}
    for first, second in (("train", "validation"), ("train", "test"), ("validation", "test")):
        if episode_sets[first] & episode_sets[second]:
            raise AssertionError("A positive silence episode crosses model splits")
    assert not any(name.endswith("_id") or name in ("y", "silence_H_day") for name in FEATURES)
    return {"all_splits_active": True, "train_targets_purged": True, "validation_targets_purged": True,
            "positive_episodes_disjoint": True, "identifier_features": False}


def select_active_models(train, validation, active_days, seed):
    assert_active(train, active_days)
    assert_active(validation, active_days)
    fitted, winner, candidates = select_models(train, validation, seed, include_frequency=True)
    # A constant fallback is not reported as a trained logistic/tree model.
    available = {name: model for name, model in fitted.items() if name == "prevalence" or not model.fallback}
    if winner not in available or validation.y.nunique() < 2:
        winner = "prevalence"
    return available, winner, candidates
