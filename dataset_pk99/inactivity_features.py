"""Point-in-time account features and fully observed future inactivity labels."""

import numpy as np
import pandas as pd

from .eda import ROUTINE_SYMBOLS, SCOPES

WINDOWS = (30, 90, 180)
BASE_FEATURES = (
    "account_age_days", "observed_history_days", "recency_days", "transactions_to_T",
    "gap_mean_days", "gap_std_days", "gap_max_days", "last_balance",
    "balance_age_days", "balance_mean_180d", "balance_std_180d",
    "frequency_change_30d", "frequency_ratio_30d", "monthly_count_std_180d",
    "monthly_count_slope_180d",
)
FEATURES = BASE_FEATURES + tuple(
    f"{name}_{window}d" for window in WINDOWS for name in
    ("count", "active_days", "amount_sum", "amount_mean", "amount_std", "inflow", "outflow")
)


def validate_financial(transactions):
    frame = transactions.copy()
    for column in ("amount", "balance"):
        frame[column] = pd.to_numeric(frame[column], errors="raise")
        if not np.isfinite(frame[column]).all():
            raise ValueError(f"Non-finite {column}")
    if (frame.amount < 0).any():
        raise ValueError("Expected nonnegative transaction amounts")
    if not frame.type.isin(["PRIJEM", "VYDAJ", "VYBER"]).all():
        raise ValueError("Unknown transaction direction")
    return frame


def activity_subset(transactions, scope):
    if scope not in SCOPES:
        raise ValueError(f"Unknown activity scope: {scope}")
    if scope == "all_transactions":
        return transactions
    return transactions.loc[~transactions.k_symbol.isin(ROUTINE_SYMBOLS)]


def _prefix(values):
    return np.r_[0., np.cumsum(values, dtype=float)]


def _moments(values, left, right):
    n = right - left
    total = _prefix(values)[right] - _prefix(values)[left]
    square = _prefix(np.square(values))[right] - _prefix(np.square(values))[left]
    mean = np.divide(total, n, out=np.full(len(n), np.nan), where=n > 0)
    variance = np.divide(square, n, out=np.full(len(n), np.nan), where=n > 0) - mean**2
    return total, mean, np.sqrt(np.maximum(variance, 0))


def build_features(accounts, transactions, dates, observation_start, scope):
    """Every slice is right-inclusive at T; no per-account terminal date is used."""
    refs = pd.DatetimeIndex(dates).to_numpy(dtype="datetime64[ns]")
    all_groups = dict(tuple(transactions.groupby("account_id", sort=False)))
    selected = activity_subset(transactions, scope)
    groups = dict(tuple(selected.groupby("account_id", sort=False)))
    parts = []
    empty = transactions.iloc[:0]
    for account in accounts.itertuples(index=False):
        group = groups.get(account.account_id, empty).sort_values(["trans_date", "trans_id"])
        all_group = all_groups.get(account.account_id, empty).sort_values(["trans_date", "trans_id"])
        activity = group.trans_date.to_numpy(dtype="datetime64[ns]")
        n = np.searchsorted(activity, refs, side="right")
        last = np.r_[np.datetime64("NaT", "ns"), activity][n]
        observed_start = max(account.opened_at, observation_start)
        f = pd.DataFrame({"account_id": account.account_id, "snapshot_date": dates,
                          "account_age_days": (refs - account.opened_at.to_datetime64()) / np.timedelta64(1, "D"),
                          "observed_history_days": (refs - observed_start.to_datetime64()) / np.timedelta64(1, "D"),
                          "transactions_to_T": n,
                          "recency_days": (refs - last) / np.timedelta64(1, "D")})
        days = np.unique(activity)
        days_n = np.searchsorted(days, refs, side="right")
        gaps = np.diff(days) / np.timedelta64(1, "D")
        gap_n = np.maximum(days_n - 1, 0)
        _, f["gap_mean_days"], f["gap_std_days"] = _moments(gaps, np.zeros(len(n), dtype=int), gap_n)
        f["gap_max_days"] = np.r_[np.nan, np.maximum.accumulate(gaps)][gap_n]
        amount = group.amount.to_numpy(dtype=float)
        inflow = np.where(group.type.eq("PRIJEM"), amount, 0.)
        outflow = np.where(group.type.isin(["VYDAJ", "VYBER"]), amount, 0.)
        for window in WINDOWS:
            begin = refs - np.timedelta64(window, "D")
            left = np.searchsorted(activity, begin, side="right")
            f[f"count_{window}d"] = n - left
            f[f"active_days_{window}d"] = days_n - np.searchsorted(days, begin, side="right")
            total, mean, std = _moments(amount, left, n)
            f[f"amount_sum_{window}d"] = total
            f[f"amount_mean_{window}d"] = mean
            f[f"amount_std_{window}d"] = std
            f[f"inflow_{window}d"] = _prefix(inflow)[n] - _prefix(inflow)[left]
            f[f"outflow_{window}d"] = _prefix(outflow)[n] - _prefix(outflow)[left]
        edges = np.column_stack([np.searchsorted(activity, refs - np.timedelta64(k * 30, "D"), side="right")
                                 for k in range(7)])
        bins = (edges[:, :-1] - edges[:, 1:])[:, ::-1]
        f["frequency_change_30d"] = bins[:, -1] - bins[:, -2]
        f["frequency_ratio_30d"] = (bins[:, -1] + 1) / (bins[:, -2] + 1)
        f["monthly_count_std_180d"] = bins.std(axis=1)
        f["monthly_count_slope_180d"] = bins @ (np.arange(6) - 2.5) / 17.5
        all_dates = all_group.trans_date.to_numpy(dtype="datetime64[ns]")
        balance_n = np.searchsorted(all_dates, refs, side="right")
        balances = all_group.balance.to_numpy(dtype=float)
        f["last_balance"] = np.r_[np.nan, balances][balance_n]
        balance_date = np.r_[np.datetime64("NaT", "ns"), all_dates][balance_n]
        f["balance_age_days"] = (refs - balance_date) / np.timedelta64(1, "D")
        balance_left = np.searchsorted(all_dates, refs - np.timedelta64(180, "D"), side="right")
        _, f["balance_mean_180d"], f["balance_std_180d"] = _moments(balances, balance_left, balance_n)
        parts.append(f.loc[f.account_age_days >= 0])
    return pd.concat(parts, ignore_index=True).sort_values(["snapshot_date", "account_id"]).reset_index(drop=True)


def make_dataset(features, transactions, scope, horizon, observation_end, history_days=180, min_transactions=1):
    """Apply eligibility before labeling; return a mutually exclusive loss funnel."""
    history_ok = features.observed_history_days.ge(history_days)
    count_ok = features.transactions_to_T.ge(min_transactions)
    complete = features.snapshot_date.add(pd.Timedelta(days=horizon)).le(observation_end)
    frame = features.loc[history_ok & count_ok & complete].copy()
    audit = {"candidates_after_opening": len(features), "removed_history": int((~history_ok).sum()),
             "removed_transaction_count": int((history_ok & ~count_ok).sum()),
             "removed_right_censoring": int((history_ok & count_ok & ~complete).sum()),
             "eligible_snapshots": len(frame), "eligible_accounts": frame.account_id.nunique()}
    frame["label_end"] = frame.snapshot_date + pd.Timedelta(days=horizon)
    groups = {key: np.sort(g.trans_date.to_numpy(dtype="datetime64[ns]"))
              for key, g in activity_subset(transactions, scope).groupby("account_id")}
    frame["y"] = 0
    for key, g in frame.groupby("account_id"):
        activity = groups.get(key, np.array([], dtype="datetime64[ns]"))
        left = np.searchsorted(activity, g.snapshot_date.to_numpy(dtype="datetime64[ns]"), side="right")
        right = np.searchsorted(activity, g.label_end.to_numpy(dtype="datetime64[ns]"), side="right")
        frame.loc[g.index, "y"] = (right == left).astype(int)
    return frame.reset_index(drop=True), audit
