"""Account-level temporal exploration; inactivity is not verified bank churn.

Run from the repository root: python -m dataset_pk99.eda --help
Dates have day resolution. Snapshots include the entire reference day T.
"""

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import platform

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

if __package__:
    from .data import load_tables
else:
    from data import load_tables


ROOT = Path(__file__).resolve().parents[1]
ROUTINE_SYMBOLS = ("UROK", "SLUZBY", "SANKC. UROK")
SCOPES = ("all_transactions", "excluding_routine")
DAY = pd.Timedelta(days=1)


@dataclass(frozen=True)
class Config:
    history_days: tuple[int, ...] = (90, 180, 365)
    horizons: tuple[int, ...] = (90, 120, 180)
    thresholds: tuple[int, ...] = (90, 120, 180)
    min_transactions: tuple[int, ...] = (1, 5)
    snapshot_freq: str = "ME"
    snapshot_dates: tuple[str, ...] = ()
    snapshot_start: str | None = None
    snapshot_end: str | None = None
    max_recency_days: int | None = None
    reactivation_days: int = 180
    scopes: tuple[str, ...] = SCOPES


def validate_tables(tables: dict) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Fail on ambiguous account ownership, bad keys or impossible dates."""
    accounts, owners, transactions = (
        tables[name].copy() for name in ("accounts", "owners", "transactions")
    )
    for frame, keys in ((accounts, ["account_id"]), (owners, ["account_id", "client_id"]),
                        (transactions, ["trans_id", "account_id"])):
        for key in keys:
            frame[key] = pd.to_numeric(frame[key], errors="raise")
            if frame[key].isna().any() or (frame[key] % 1 != 0).any():
                raise ValueError(f"Identificador inválido: {key}")
            frame[key] = frame[key].astype("int64")
    for frame, key in ((accounts, "account_id"), (owners, "account_id"),
                       (transactions, "trans_id")):
        if frame[key].duplicated().any():
            raise ValueError(f"Chave duplicada: {key}; não será removida silenciosamente.")
    for frame in (owners, transactions):
        if not frame.account_id.isin(accounts.account_id).all():
            raise ValueError("Referência a account_id inexistente.")
    for frame, column in ((accounts, "opened_at"), (transactions, "trans_date")):
        frame[column] = pd.to_datetime(frame[column], errors="raise", format="ISO8601")
        if frame[column].isna().any():
            raise ValueError(f"Data ausente: {column}")
        if not frame[column].eq(frame[column].dt.normalize()).all():
            raise ValueError("A análise requer datas com resolução diária.")
    if transactions.empty:
        raise ValueError("Base sem transações.")
    opened = transactions.account_id.map(accounts.set_index("account_id").opened_at)
    if (transactions.trans_date < opened).any():
        raise ValueError("Há transações anteriores à abertura da conta.")
    for column in ("type", "operation", "k_symbol"):
        transactions[column] = transactions[column].fillna("").astype("string").str.strip()
    accounts = accounts.merge(owners, on="account_id", how="left", validate="one_to_one")
    accounts["client_id"] = accounts.client_id.astype("Int64")
    quality = {
        "accounts": len(accounts), "transactions": len(transactions),
        "owner_links": len(owners),
        "accounts_without_owner": int(accounts.client_id.isna().sum()),
        "owners_with_multiple_accounts": int(owners.client_id.value_counts().gt(1).sum()),
        "accounts_without_transactions": int((~accounts.account_id.isin(transactions.account_id)).sum()),
        "duplicate_account_dates": int(transactions.duplicated(["account_id", "trans_date"]).sum()),
        "observation_start": str(transactions.trans_date.min().date()),
        "observation_end": str(transactions.trans_date.max().date()),
    }
    return accounts, transactions.sort_values(["account_id", "trans_date", "trans_id"]), quality


def describe_numeric(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    return frame[columns].describe(percentiles=[.25, .5, .75, .9, .95, .99]).T.rename_axis("metric").reset_index()


def account_behavior(accounts: pd.DataFrame, transactions: pd.DataFrame,
                     start: pd.Timestamp, end: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Full-period descriptions; these MUST NOT become snapshot predictors."""
    grouped = transactions.groupby("account_id")
    metrics = grouped.agg(first_transaction=("trans_date", "min"),
                          last_transaction=("trans_date", "max"),
                          transaction_count=("trans_id", "size"),
                          active_days=("trans_date", "nunique"))
    # Same-day transactions yield zero raw gaps. Activity-day gaps remove these
    # zeros and are the basis for inactivity episodes, without losing raw counts.
    raw_gaps = grouped.trans_date.diff().dt.days.dropna()
    days = transactions[["account_id", "trans_date"]].drop_duplicates().copy()
    days["previous_date"] = days.groupby("account_id").trans_date.shift()
    days["gap_days"] = (days.trans_date - days.previous_date).dt.days
    gap_stats = days.groupby("account_id").gap_days.agg(
        gap_count="count", gap_mean="mean", gap_std="std", gap_median="median", gap_max="max"
    )
    quantiles = days.groupby("account_id").gap_days.quantile([.9, .95, .99]).unstack().reindex(columns=[.9, .95, .99])
    quantiles.columns = ["gap_p90", "gap_p95", "gap_p99"]
    result = accounts.merge(metrics, on="account_id", how="left", validate="one_to_one")
    result = result.merge(gap_stats.join(quantiles), on="account_id", how="left", validate="one_to_one")
    result[["transaction_count", "active_days", "gap_count"]] = result[
        ["transaction_count", "active_days", "gap_count"]].fillna(0).astype(int)
    result["observation_start"] = result.opened_at.clip(lower=start)
    result["observed_days"] = (end - result.observation_start).dt.days.clip(lower=0)
    result["days_since_first_transaction"] = (end - result.first_transaction).dt.days
    result["active_span_days"] = (result.last_transaction - result.first_transaction).dt.days
    result["opening_to_first_days"] = (result.first_transaction - result.opened_at).dt.days
    result["recency_days"] = (end - result.last_transaction).dt.days
    result["transactions_per_30_observed_days"] = result.transaction_count * 30 / (result.observed_days + 1)
    result["transactions_per_30_days_since_first"] = result.transaction_count * 30 / (result.days_since_first_transaction + 1)
    completed = days.dropna(subset=["previous_date"]).rename(
        columns={"previous_date": "gap_start", "trans_date": "next_transaction"})
    completed = completed[["account_id", "gap_start", "next_transaction", "gap_days"]].copy()
    completed["right_censored"] = False
    terminal = metrics.reset_index()[["account_id", "last_transaction"]].rename(
        columns={"last_transaction": "gap_start"})
    terminal["next_transaction"] = pd.NaT
    terminal["gap_days"] = (end - terminal.gap_start).dt.days
    terminal["right_censored"] = True
    episodes = pd.concat([completed, terminal], ignore_index=True)
    gap_distribution = pd.concat([
        raw_gaps.describe(percentiles=[.5, .9, .95, .99]).rename("raw_transaction_gap_days"),
        completed.gap_days.describe(percentiles=[.5, .9, .95, .99]).rename("active_day_gap_days"),
    ], axis=1).rename_axis("statistic").reset_index()
    return result, episodes, gap_distribution


def summarize_gaps(episodes: pd.DataFrame, thresholds: tuple[int, ...],
                   end: pd.Timestamp, followup: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, counts = [], []
    for threshold in thresholds:
        long = episodes.loc[episodes.gap_days > threshold].copy()
        returned = long.loc[~long.right_censored]
        crossing = long.gap_start + threshold * DAY
        comparable = crossing + followup * DAY <= end
        returned_in_window = long.next_transaction.le(crossing + followup * DAY)
        rows.append({
            "threshold_days": threshold, "accounts_with_long_gap": long.account_id.nunique(),
            "accounts_reactivated": returned.account_id.nunique(),
            "account_observed_return_fraction": returned.account_id.nunique() / long.account_id.nunique() if len(long) else np.nan,
            "episodes": len(long), "completed_episodes": len(returned),
            "right_censored_episodes": int(long.right_censored.sum()),
            "episode_observed_return_fraction": len(returned) / len(long) if len(long) else np.nan,
            "fixed_followup_days": followup, "fixed_followup_episodes": int(comparable.sum()),
            "fixed_followup_returns": int((comparable & returned_in_window).sum()),
            "fixed_followup_return_fraction": returned_in_window[comparable].mean(),
            "completed_gap_median": returned.gap_days.median(),
            "completed_gap_p90": returned.gap_days.quantile(.9),
            "completed_gap_max": returned.gap_days.max(),
        })
        per_account = long.groupby("account_id").agg(
            episodes=("gap_days", "size"), censored_episodes=("right_censored", "sum"))
        per_account["completed_episodes"] = per_account.episodes - per_account.censored_episodes
        per_account["threshold_days"] = threshold
        counts.append(per_account.reset_index())
    return pd.DataFrame(rows), pd.concat(counts, ignore_index=True)


def snapshot_calendar(config: Config, start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    if config.snapshot_dates:
        dates = pd.DatetimeIndex(pd.to_datetime(list(config.snapshot_dates), errors="raise"))
    else:
        dates = pd.date_range(config.snapshot_start or start, config.snapshot_end or end,
                              freq=config.snapshot_freq)
    if len(dates) == 0 or dates.hasnans or (dates != dates.normalize()).any():
        raise ValueError("Calendário vazio ou com datas inválidas; use datas sem horário.")
    if (dates < start).any() or (dates > end).any():
        raise ValueError("Snapshots devem estar dentro do período observado.")
    return dates.drop_duplicates().sort_values()


def build_snapshots(accounts: pd.DataFrame, transactions: pd.DataFrame,
                    dates: pd.DatetimeIndex, start: pd.Timestamp,
                    end: pd.Timestamp, config: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Features use <= T; future labels alone use (T, T+H].

    searchsorted works per account on the whole calendar, avoiding a large
    transaction x snapshot join. It preserves multiple transactions per day.
    """
    histories = {key: group.trans_date.to_numpy(dtype="datetime64[ns]")
                 for key, group in transactions.groupby("account_id", sort=False)}
    feature_parts, label_parts = [], []
    refs = dates.to_numpy(dtype="datetime64[ns]")
    empty = np.array([], dtype="datetime64[ns]")
    for account in accounts.itertuples(index=False):
        activity = histories.get(account.account_id, empty)
        n = np.searchsorted(activity, refs, side="right")
        has_history = n > 0
        last = np.full(len(dates), np.datetime64("NaT"), dtype="datetime64[ns]")
        first = last.copy()
        next_date = last.copy()
        last[has_history] = activity[n[has_history] - 1]
        if len(activity):
            first[has_history] = activity[0]
        has_next = n < len(activity)
        next_date[has_next] = activity[n[has_next]]
        observed = np.maximum(0, (refs - np.datetime64(max(account.opened_at, start), "ns")) / np.timedelta64(1, "D"))
        f = pd.DataFrame({"account_id": account.account_id, "snapshot_date": dates,
                          "opened_at": account.opened_at, "first_transaction_to_T": first,
                          "last_transaction_to_T": last, "transactions_to_T": n,
                          "observed_history_days": observed,
                          "history_since_first_days": (refs - first) / np.timedelta64(1, "D"),
                          "recency_days": (refs - last) / np.timedelta64(1, "D")})
        f["transactions_per_30_observed_days"] = n * 30 / (observed + 1)
        for window in config.thresholds:
            previous_n = np.searchsorted(activity, refs - np.timedelta64(window, "D"), side="right")
            f[f"transactions_last_{window}d"] = n - previous_n
        f = f.loc[f.snapshot_date >= account.opened_at]
        feature_parts.append(f)
        for horizon in config.horizons:
            finish = dates + horizon * DAY
            future_n = np.searchsorted(activity, finish.to_numpy(dtype="datetime64[ns]"), side="right") - n
            labels = pd.DataFrame({"account_id": account.account_id, "snapshot_date": dates,
                                   "horizon_days": horizon, "label_end": finish,
                                   "future_transaction_count": future_n,
                                   "future_inactivity_flag": (future_n == 0).astype(int),
                                   "next_transaction_after_T": next_date})
            # Incomplete windows are NOT negative or positive labels.
            labels = labels.loc[(finish <= end) & (dates >= account.opened_at)]
            label_parts.append(labels)
    return pd.concat(feature_parts, ignore_index=True), pd.concat(label_parts, ignore_index=True)


def eligible_mask(frame: pd.DataFrame, history: int, minimum: int, config: Config) -> pd.Series:
    mask = (frame.observed_history_days.ge(history) & frame.history_since_first_days.ge(history)
            & frame.transactions_to_T.ge(minimum))
    if config.max_recency_days is not None:
        mask &= frame.recency_days.le(config.max_recency_days)
    return mask


def target_statistics(frame: pd.DataFrame, end: pd.Timestamp, config: Config) -> dict:
    positive = frame.loc[frame.future_inactivity_flag.eq(1)]
    returned = positive.next_transaction_after_T.notna()
    followup_end = positive.label_end + config.reactivation_days * DAY
    full_followup = followup_end <= end
    returned_fixed = positive.next_transaction_after_T.le(followup_end)
    # Runs are sequences in the eligible calendar, not independent events.
    ordered = frame.sort_values(["account_id", "snapshot_date"])
    is_positive = ordered.future_inactivity_flag.eq(1)
    starts = is_positive & (~is_positive.shift(fill_value=False)
                           | ordered.account_id.ne(ordered.account_id.shift()))
    return {
        "observations": len(frame), "accounts": frame.account_id.nunique(),
        "positives": len(positive), "positive_accounts": positive.account_id.nunique(),
        "prevalence": positive.shape[0] / len(frame) if len(frame) else np.nan,
        "positive_runs": int(starts.sum()),
        "positive_already_inactive_at_T": int(positive.recency_days.ge(positive.horizon_days).sum()),
        "positive_snapshots_with_observed_return": int(returned.sum()),
        "positive_accounts_with_observed_return": positive.loc[returned, "account_id"].nunique(),
        "observed_return_fraction": returned.mean(),
        "positive_fixed_followup_observations": int(full_followup.sum()),
        "positive_fixed_followup_returns": int((returned_fixed & full_followup).sum()),
        "fixed_followup_return_fraction": returned_fixed[full_followup].mean(),
        "post_label_followup_median_days": (end - positive.label_end).dt.days.median(),
    }


def evaluate_targets(features: pd.DataFrame, labels: pd.DataFrame,
                     end: pd.Timestamp, config: Config) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    summaries, by_date, eligibility = [], [], []
    joined = labels.merge(features, on=["account_id", "snapshot_date"], validate="many_to_one")
    common_last_T = end - max(config.horizons) * DAY
    for history in config.history_days:
        for minimum in config.min_transactions:
            for horizon in config.horizons:
                complete = joined.loc[joined.horizon_days.eq(horizon)]
                chosen = complete.loc[eligible_mask(complete, history, minimum, config)]
                key = {"history_days": history, "min_transactions": minimum, "horizon_days": horizon}
                for calendar, frame in (("all_complete", chosen),
                                        ("common_calendar", chosen.loc[chosen.snapshot_date <= common_last_T])):
                    summaries.append({**key, "calendar": calendar, **target_statistics(frame, end, config)})
                for date in features.snapshot_date.drop_duplicates().sort_values():
                    candidates = features.loc[features.snapshot_date.eq(date)]
                    history_ok = candidates.observed_history_days.ge(history) & candidates.history_since_first_days.ge(history)
                    count_ok = history_ok & candidates.transactions_to_T.ge(minimum)
                    recency_ok = eligible_mask(candidates, history, minimum, config)
                    full = date + horizon * DAY <= end
                    eligibility.append({**key, "snapshot_date": date, "opened_accounts": len(candidates),
                                        "history_eligible": int(history_ok.sum()),
                                        "transaction_count_eligible": int(count_ok.sum()),
                                        "recency_eligible": int(recency_ok.sum()),
                                        "complete_future_window": bool(full),
                                        "eligible": int(recency_ok.sum()) if full else 0})
                    sample = chosen.loc[chosen.snapshot_date.eq(date)]
                    by_date.append({**key, "snapshot_date": date, "observations": len(sample),
                                    "positives": int(sample.future_inactivity_flag.sum()),
                                    "prevalence": sample.future_inactivity_flag.mean()})
    return pd.DataFrame(summaries), pd.DataFrame(by_date), pd.DataFrame(eligibility)


def save_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, float_format="%.8g")


def plot_scope(metrics: pd.DataFrame, episodes: pd.DataFrame, by_date: pd.DataFrame,
               config: Config, output: Path, scope: str) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.8), layout="constrained")
    completed = episodes.loc[~episodes.right_censored, "gap_days"].to_numpy()
    if len(completed):
        values, counts = np.unique(completed, return_counts=True)
        survival = (len(completed) - counts.cumsum() + counts) / len(completed)
        axes[0].step(values, survival, where="pre")
        axes[0].set_xscale("log")
        axes[0].set_yscale("log")
        for threshold in config.thresholds:
            axes[0].axvline(threshold, color="gray", alpha=.4, linestyle=":")
    axes[0].set(title="Gaps encerrados entre dias ativos", xlabel="Gap (dias; linhas = thresholds)", ylabel="Fração com gap ≥ x (escala log)")
    axes[1].hist(metrics.recency_days.dropna(), bins=30, color="#326c85", log=True)
    axes[1].set(title="Recência ao final da base", xlabel="Dias desde a última transação", ylabel="Contas (escala log)")
    history = 180 if 180 in config.history_days else config.history_days[0]
    minimum = 5 if 5 in config.min_transactions else config.min_transactions[0]
    selected = by_date.loc[by_date.history_days.eq(history) & by_date.min_transactions.eq(minimum)]
    for horizon, group in selected.groupby("horizon_days"):
        axes[2].plot(group.snapshot_date, group.prevalence * 100, label=f"H={horizon} dias")
    axes[2].set(title=f"Inatividade futura: histórico ≥ {history} d; n ≥ {minimum}", xlabel="Data T", ylabel="Prevalência (%)")
    axes[2].legend()
    for ax in axes:
        ax.grid(alpha=.2)
    fig.suptitle(f"Berka — {scope} — análise exploratória, sem rótulo de encerramento")
    fig.savefig(output / "overview.png", dpi=150)
    plt.close(fig)


def textual_report(quality: dict, summary: pd.DataFrame, gaps: pd.DataFrame) -> str:
    sections = ["BERKA: EDA TEMPORAL EXPLORATÓRIA", json.dumps(quality, indent=2, ensure_ascii=False)]
    for scope in summary.activity_scope.unique():
        sections.append(f"ATIVIDADE: {scope}")
        sections.append("Gaps estritamente superiores ao threshold; censura incluída no denominador:")
        sections.append(gaps.loc[gaps.activity_scope.eq(scope), [
            "threshold_days", "accounts_with_long_gap", "accounts_reactivated",
            "episodes", "completed_episodes", "right_censored_episodes",
            "fixed_followup_episodes", "fixed_followup_returns",
        ]].to_string(index=False))
        for calendar in ("all_complete", "common_calendar"):
            sections.append(f"Targets: {calendar}; prevalência por snapshot (%), não por cliente:")
            frame = summary.loc[summary.activity_scope.eq(scope) & summary.calendar.eq(calendar)].copy()
            frame["prevalence_pct"] = frame.prevalence * 100
            sections.append(frame[["history_days", "min_transactions", "horizon_days",
                                   "observations", "positives", "positive_accounts", "prevalence_pct",
                                   "positive_runs"]].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    sections.extend([
        "LIMITAÇÕES: ausência de transações não comprova encerramento. O fim global da base\n"
        "é um limite administrativo assumido, não prova de captura contínua por conta.",
        "Retornos até o fim têm follow-up desigual; consulte também as taxas com follow-up fixo\n"
        "e os denominadores nos CSVs. Gaps encerrados retornam por construção.",
        "Contas/snapshots e janelas sobrepostas não são independentes. Uma futura avaliação deve\n"
        "separar contas e tempo, purgar rótulos que atravessem o corte e nunca usar métricas\n"
        "do período inteiro como preditores. Não dividir linhas aleatoriamente em treino/teste.",
        "Excluir juros/tarifas não identifica necessariamente ação deliberada do cliente.\n"
        "Nenhuma configuração foi escolhida para ajustar a proporção de positivos.",
    ])
    return "\n\n".join(sections) + "\n"


def run_analysis(tables: dict, config: Config, output: Path, provenance: dict) -> dict:
    accounts, transactions, quality = validate_tables(tables)
    start, end = transactions.trans_date.min(), transactions.trans_date.max()
    dates = snapshot_calendar(config, start, end)
    output.mkdir(parents=True, exist_ok=True)
    composition = transactions.groupby(["type", "operation", "k_symbol"], dropna=False).size().reset_index(name="transactions")
    composition["excluded_as_routine"] = composition.k_symbol.isin(ROUTINE_SYMBOLS)
    save_csv(composition, output / "transaction_composition.csv")
    save_csv(transactions.groupby(transactions.trans_date.dt.to_period("M")).agg(
        transactions=("trans_id", "size"), active_accounts=("account_id", "nunique")
    ).reset_index(), output / "monthly_coverage.csv")
    summaries, gap_summaries = [], []
    for scope in config.scopes:
        print(f"Analisando {scope}...", flush=True)
        selected = transactions if scope == "all_transactions" else transactions.loc[~transactions.k_symbol.isin(ROUTINE_SYMBOLS)]
        directory = output / scope
        directory.mkdir(exist_ok=True)
        metrics, episodes, gap_distribution = account_behavior(accounts, selected, start, end)
        gaps, gap_counts = summarize_gaps(episodes, config.thresholds, end, config.reactivation_days)
        features, labels = build_snapshots(accounts, selected, dates, start, end, config)
        summary, by_date, eligibility = evaluate_targets(features, labels, end, config)
        # Export only labels eligible under at least the least restrictive
        # configured history/count rule. Stricter rules are applied in summaries.
        label_candidates = labels.merge(features, on=["account_id", "snapshot_date"], validate="many_to_one")
        export_labels = label_candidates.loc[
            eligible_mask(label_candidates, min(config.history_days), min(config.min_transactions), config), labels.columns]
        numeric = [column for column in metrics.select_dtypes("number").columns if column not in ("account_id", "client_id")]
        for name, frame in {
            "account_metrics.csv": metrics,
            "account_distribution.csv": describe_numeric(metrics, numeric),
            "gap_distribution.csv": gap_distribution,
            "gap_summary.csv": gaps, "gap_counts_by_account.csv": gap_counts,
            "long_gap_episodes.csv": episodes.loc[episodes.gap_days > min(config.thresholds)],
            "features_by_snapshot.csv.gz": features, "future_labels.csv.gz": export_labels,
            "target_by_snapshot.csv": by_date, "eligibility_by_snapshot.csv": eligibility,
            "target_summary.csv": summary,
        }.items():
            save_csv(frame, directory / name)
        plot_scope(metrics, episodes, by_date, config, directory, scope)
        summaries.append(summary.assign(activity_scope=scope))
        gap_summaries.append(gaps.assign(activity_scope=scope))
        print(f"  {len(selected):,} transações; {len(features):,} conta-snapshots antes da elegibilidade.", flush=True)
    summary = pd.concat(summaries, ignore_index=True)
    gaps = pd.concat(gap_summaries, ignore_index=True)
    save_csv(summary, output / "target_summary.csv")
    save_csv(gaps, output / "gap_summary.csv")
    manifest = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "config": asdict(config),
                "snapshot_dates": [str(date.date()) for date in dates], "data_quality": quality,
                "data_provenance": provenance, "excluded_routine_symbols": ROUTINE_SYMBOLS,
                "python": platform.python_version(),
                "packages": {name: importlib.metadata.version(name) for name in
                             ("numpy", "pandas", "matplotlib", "mysql-connector-python")}}
    (output / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    text = textual_report(quality, summary, gaps)
    (output / "report.txt").write_text(text, encoding="utf-8")
    print(text)
    print(f"Outputs: {output.resolve()}")
    return manifest


def parse_args() -> tuple[argparse.Namespace, Config]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("database", "cache"), default="database")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "data" / "berka")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs" / "berka" / datetime.now().strftime("%Y%m%d_%H%M%S"))
    for flag, default in (("history-days", (90, 180, 365)), ("horizons", (90, 120, 180)),
                          ("thresholds", (90, 120, 180)), ("min-transactions", (1, 5))):
        parser.add_argument(f"--{flag}", nargs="+", type=int, default=default)
    parser.add_argument("--snapshot-freq", default="ME", help="Frequência pandas, por exemplo ME ou QS")
    parser.add_argument("--snapshot-dates", nargs="+", default=())
    parser.add_argument("--snapshot-start")
    parser.add_argument("--snapshot-end")
    parser.add_argument("--max-recency-days", type=int, help="Filtro opcional conhecido em T; ausente por padrão")
    parser.add_argument("--reactivation-days", type=int, default=180)
    parser.add_argument("--scopes", nargs="+", choices=SCOPES, default=SCOPES)
    args = parser.parse_args()
    for name in ("history_days", "horizons", "thresholds", "min_transactions"):
        values = sorted(set(getattr(args, name)))
        if min(values) < 1:
            parser.error(f"{name}: valores devem ser positivos.")
        setattr(args, name, tuple(values))
    if args.reactivation_days < 1 or (args.max_recency_days is not None and args.max_recency_days < 0):
        parser.error("Follow-up deve ser positivo; recência máxima deve ser não negativa.")
    if args.snapshot_dates and (args.snapshot_start or args.snapshot_end):
        parser.error("Use datas explícitas OU limites para o calendário regular.")
    config = Config(**{name: tuple(getattr(args, name)) if name in ("scopes", "snapshot_dates")
                       else getattr(args, name) for name in Config.__dataclass_fields__})
    return args, config


def main() -> None:
    args, config = parse_args()
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise SystemExit("Escolha um --output-dir vazio para não misturar execuções.")
    try:
        tables, provenance = load_tables(args.source, args.cache_dir)
        run_analysis(tables, config, args.output_dir, provenance)
    except (OSError, ValueError) as error:
        raise SystemExit(f"EDA não concluída: {error}") from error


if __name__ == "__main__":
    main()
