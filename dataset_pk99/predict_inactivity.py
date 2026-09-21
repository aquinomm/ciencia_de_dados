"""CPU temporal dormancy prediction. Run: python -m dataset_pk99.predict_inactivity."""

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import precision_recall_curve, roc_curve
from threadpoolctl import threadpool_limits

from .data import file_hash, load_tables
from .eda import SCOPES, validate_tables
from .inactivity_features import FEATURES, build_features, make_dataset, validate_financial
from .inactivity_evaluation import (
    CI_METRICS, MODELS, MetricEvaluator, clustered_bootstrap, select_models, summarize, temporal_split,
)

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Config:
    snapshot_freq: str = "ME"
    history_days: int = 180
    min_transactions: int = 1
    horizons: tuple[int, ...] = (90, 120, 180)
    scopes: tuple[str, ...] = SCOPES
    validation_start: str = "1997-04-01"
    test_start: str = "1998-01-01"
    seed: int = 20260920
    bootstrap_repetitions: int = 1000
    threads: int = 4
    stability: bool = True


def _json_value(value):
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if value is pd.NaT:
        return None
    return value


def save_json(value, path):
    path.write_text(json.dumps(_json_value(value), indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def save_csv(frame, path):
    frame.to_csv(path, index=False, compression={"method": "gzip", "mtime": 0} if path.suffix == ".gz" else None)


def calibration_table(y, probabilities):
    frame = pd.DataFrame({"y": np.asarray(y), "probability": probabilities})
    # Fixed probability bins show the rare-event region; empty bins are omitted.
    frame["bin"] = pd.cut(frame.probability, [-1e-12, .0001, .001, .01, .05, .1, .25, .5, .75, 1.], include_lowest=True)
    return frame.groupby("bin", observed=True).agg(
        snapshots=("y", "size"), positives=("y", "sum"),
        mean_probability=("probability", "mean"), observed_rate=("y", "mean")).reset_index()


def plot_evaluation(frame, scores, directory):
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.6))
    calibration_parts = []
    for name, p in scores.items():
        if frame.y.nunique() == 2:
            precision, recall, _ = precision_recall_curve(frame.y, p)
            fpr, tpr, _ = roc_curve(frame.y, p)
            axes[0].step(recall, precision, where="post", label=name)
            axes[1].plot(fpr, tpr, label=name)
        calibration = calibration_table(frame.y, p)
        calibration_parts.append(calibration.assign(model=name))
        axes[2].plot(calibration.mean_probability, calibration.observed_rate, "o-", label=name)
    axes[0].axhline(frame.y.mean(), color="gray", linestyle="--", label="test prevalence")
    axes[0].set(xlabel="Recall", ylabel="Precision", title="TEST precision-recall", ylim=(0, 1.02))
    axes[1].plot([0, 1], [0, 1], "k--", linewidth=.8)
    axes[1].set(xlabel="False positive rate", ylabel="True positive rate", title="TEST ROC")
    axes[2].plot([0, 1], [0, 1], "k--", linewidth=.8)
    axes[2].set(xlabel="Mean predicted probability", ylabel="Observed frequency", title="TEST calibration")
    for ax in axes:
        ax.grid(alpha=.2)
    axes[0].legend(fontsize=7, loc="upper right")
    fig.tight_layout()
    fig.savefig(directory / "test_curves.png", dpi=160)
    plt.close(fig)
    save_csv(pd.concat(calibration_parts), directory / "calibration.csv")


def model_record(model):
    return {"parameters": model.estimator.get_params(deep=False) if model.name == "hist_gradient_boosting" and not model.fallback else model.params,
            "threshold": model.threshold, "recency_cutoff_days": model.recency_cutoff_days,
            "single_class_train_fallback": model.fallback, "validation_metrics": model.validation_metrics}


def stability_evaluation(frame, config, scope, horizon):
    rows, split_rows, predictions, candidates = [], [], [], []
    # Offsets from the reserved test date keep every evaluation label before TEST.
    final = pd.Timestamp(config.test_start)
    for name, months in (("expanding_1", 12), ("expanding_2", 9)):
        evaluation_start = final - pd.DateOffset(months=months)
        evaluation_end = evaluation_start + pd.DateOffset(months=3) - pd.Timedelta(days=1)
        validation_start = evaluation_start - pd.DateOffset(months=9)
        development = frame.loc[(frame.snapshot_date <= evaluation_end) & (frame.label_end < final)]
        splits, definitions, _ = temporal_split(development, validation_start, evaluation_start, evaluation_end)
        selected, winner, search = select_models(splits["train"], splits["validation"], config.seed)
        key = {"scope": scope, "horizon": horizon, "window": name}
        split_rows.extend([{**key, **row} for row in definitions])
        candidates.extend([{**key, **row} for row in search])
        for model_name, model in selected.items():
            p = model.predict(splits["test"])
            rows.append({**key, "model": model_name, "selected_on_validation": model_name == winner,
                         "single_class_train_fallback": model.fallback,
                         "train_positive_accounts": summarize(splits["train"])["positive_accounts"],
                         "threshold": model.threshold, **summarize(splits["test"]),
                         **MetricEvaluator(splits["test"].y, p, model.threshold).compute()})
            predictions.append(splits["test"][["account_id", "snapshot_date", "label_end", "y"]].assign(
                **key, model=model_name, probability=p, predicted=(p >= model.threshold).astype(int)))
    return rows, split_rows, predictions, candidates


def run_analysis(tables, provenance, config, output):
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty output directory")
    output.mkdir(parents=True, exist_ok=True)
    accounts, transactions, quality = validate_tables(tables)
    transactions = validate_financial(transactions)
    start, end = transactions.trans_date.min(), transactions.trans_date.max()
    dates = pd.date_range(start, end, freq=config.snapshot_freq)
    if not len(dates):
        raise ValueError("Empty snapshot calendar")
    source_paths = [*sorted((ROOT / "dataset_pk99").glob("*.py")), ROOT / "requirements.txt"]
    source_hashes = {str(p.relative_to(ROOT)): file_hash(p) for p in source_paths}
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    protocol = {"created_at_utc": datetime.now(timezone.utc), "config": asdict(config),
                "features": FEATURES, "data_quality": quality, "data_provenance": provenance,
                "snapshot_dates": dates.tolist(), "source_sha256": source_hashes,
                "git_head": git.stdout.strip(), "python": platform.python_version(),
                "platform": platform.platform(), "cpu_count": os.cpu_count(),
                "packages": {name: importlib.metadata.version(name) for name in
                             ("numpy", "pandas", "matplotlib", "scikit-learn", "scipy", "joblib", "threadpoolctl", "mysql-connector-python")},
                "selection_metric": "validation average_precision; tie: lower Brier; tie: fixed candidate order",
                "threshold_metric": "validation F2; tie: largest threshold",
                "refit_after_validation": False, "rebalancing": None,
                "purge_rule": "previous label_end < next period start",
                "bootstrap": {"cluster": "account_id", "resample_size": "number of unique evaluated accounts",
                              "repetitions": config.bootstrap_repetitions, "seed": config.seed, "ci": .95,
                              "method": "percentile, unstratified, conditional on fitted model and threshold"}}
    save_json(protocol, output / "protocol.json")
    experiments, eligibility, split_rows, purges, searches = {}, [], [], [], []
    stability, stability_splits, stability_predictions, stability_search = [], [], [], []
    selections = {}
    with threadpool_limits(limits=config.threads):
        for scope in config.scopes:
            print(f"Features: {scope}", flush=True)
            features = build_features(accounts, transactions, dates, start, scope)
            save_csv(features, output / f"features_{scope}.csv.gz")
            for horizon in config.horizons:
                key = {"scope": scope, "horizon": horizon}
                name = f"{scope}_h{horizon}"
                directory = output / name
                directory.mkdir()
                dataset, audit = make_dataset(features, transactions, scope, horizon, end,
                                              config.history_days, config.min_transactions)
                eligibility.append({**key, **audit})
                splits, definitions, purge = temporal_split(dataset, config.validation_start, config.test_start,
                                                             summarize_test=False)
                split_rows.extend([{**key, **row} for row in definitions])
                purges.extend([{**key, **row} for row in purge])
                print(f"Selection: {name}", flush=True)
                models, winner, candidates = select_models(splits["train"], splits["validation"], config.seed)
                searches.extend([{**key, **row} for row in candidates])
                save_csv(dataset[["account_id", "snapshot_date", "label_end", "y"]], directory / "labels.csv.gz")
                save_json({n: model_record(m) for n, m in models.items()}, directory / "selection.json")
                joblib.dump(models, directory / "fitted_models.joblib")
                selections[name] = {"winner": winner, "selection_sha256": file_hash(directory / "selection.json"),
                                    "fitted_models_sha256": file_hash(directory / "fitted_models.joblib")}
                experiments[name] = (splits, models, winner, key, directory)
                validation_predictions = []
                for model_name, model in models.items():
                    p = model.predict(splits["validation"])
                    validation_predictions.append(splits["validation"][["account_id", "snapshot_date", "label_end", "y"]].assign(
                        model=model_name, probability=p, predicted=(p >= model.threshold).astype(int)))
                save_csv(pd.concat(validation_predictions), directory / "validation_predictions.csv.gz")
                if config.stability:
                    print(f"Expanding windows: {name}", flush=True)
                    rows, defs, pred, search = stability_evaluation(dataset, config, scope, horizon)
                    stability.extend(rows)
                    stability_splits.extend(defs)
                    stability_predictions.extend(pred)
                    stability_search.extend(search)
        save_csv(pd.DataFrame(eligibility), output / "eligibility.csv")
        save_csv(pd.DataFrame(purges), output / "purges.csv")
        save_json(searches, output / "validation_candidates.json")
        if config.stability:
            save_csv(pd.DataFrame(stability), output / "stability_metrics.csv")
            save_csv(pd.DataFrame(stability_splits), output / "stability_splits.csv")
            save_csv(pd.concat(stability_predictions), output / "stability_predictions.csv.gz")
            save_json(stability_search, output / "stability_candidates.json")
        save_json({"frozen_at_utc": datetime.now(timezone.utc), "experiments": selections,
                   "protocol_sha256": file_hash(output / "protocol.json")}, output / "frozen_selection.json")
        print("All selections frozen. Evaluating TEST.", flush=True)
        for row in split_rows:
            if row["split"] == "test":
                row.update(summarize(experiments[f"{row['scope']}_h{row['horizon']}"][0]["test"]))
        save_csv(pd.DataFrame(split_rows), output / "splits.csv")
        metrics, intervals, diagnostics, monthly, persistence, deltas = [], [], [], [], [], []
        common_end = end - pd.Timedelta(days=max(config.horizons))
        for name, (splits, models, winner, key, directory) in experiments.items():
            print(f"TEST and account bootstrap: {name}", flush=True)
            test = splits["test"]
            scores, predictions, bootstrap_draws = {}, [], {}
            train_positive_ids = set(splits["train"].loc[splits["train"].y.eq(1), "account_id"])
            persistence.append({**key, **summarize(test),
                                "positive_already_inactive_H": int((test.y.eq(1) & test.recency_days.ge(key["horizon"])).sum()),
                                "positive_recent_30d": int((test.y.eq(1) & test.recency_days.le(30)).sum()),
                                "positive_accounts_seen_positive_in_train": len(set(test.loc[test.y.eq(1), "account_id"]) & train_positive_ids)})
            for model_name, model in models.items():
                p = model.predict(test)
                scores[model_name] = p
                model_key = {**key, "model": model_name, "selected_on_validation": model_name == winner}
                metrics.append({**model_key, "threshold": model.threshold, **summarize(test),
                                **MetricEvaluator(test.y, p, model.threshold).compute()})
                ci, draws = clustered_bootstrap(test, p, model.threshold, config.bootstrap_repetitions, config.seed)
                intervals.extend([{**model_key, **row} for row in ci])
                bootstrap_draws[model_name] = draws
                predictions.append(test[["account_id", "snapshot_date", "label_end", "y", "recency_days"]].assign(
                    model=model_name, probability=p, predicted=(p >= model.threshold).astype(int)))
                for cohort, mask in {
                    "recent_activity_30d": test.recency_days.le(30),
                    "not_already_inactive_H": test.recency_days.lt(key["horizon"]),
                    "common_test_calendar": test.snapshot_date.le(common_end),
                    "account_not_positive_in_train": ~test.account_id.isin(train_positive_ids),
                }.items():
                    if mask.any():
                        subset = test.loc[mask]
                        diagnostics.append({**model_key, "cohort": cohort, **summarize(subset),
                                            **MetricEvaluator(subset.y, p[mask], model.threshold).compute()})
                for date in test.snapshot_date.unique():
                    mask = test.snapshot_date.eq(date)
                    monthly.append({**model_key, "snapshot_date": date, **summarize(test.loc[mask]),
                                    **MetricEvaluator(test.loc[mask, "y"], p[mask], model.threshold).compute()})
            for baseline in ("prevalence", "recency"):
                for metric in ("average_precision", "brier"):
                    differences = bootstrap_draws[winner][metric] - bootstrap_draws[baseline][metric]
                    deltas.append({**key, "selected_model": winner, "baseline": baseline, "metric": metric,
                                   "difference": (
                                       MetricEvaluator(test.y, scores[winner], models[winner].threshold).compute()[metric] -
                                       MetricEvaluator(test.y, scores[baseline], models[baseline].threshold).compute()[metric]),
                                   "ci_low": differences.quantile(.025), "ci_high": differences.quantile(.975),
                                   "valid_replicates": differences.notna().sum()})
            save_csv(pd.concat(predictions), directory / "test_predictions.csv.gz")
            save_csv(pd.concat([d.assign(model=n, replicate=np.arange(len(d))) for n, d in bootstrap_draws.items()]), directory / "bootstrap_draws.csv.gz")
            plot_evaluation(test, scores, directory)
        for filename, rows in (("test_metrics", metrics), ("test_confidence_intervals", intervals),
                               ("diagnostic_cohorts", diagnostics), ("test_monthly_metrics", monthly),
                               ("persistence_diagnostics", persistence), ("paired_baseline_differences", deltas)):
            save_csv(pd.DataFrame(rows), output / f"{filename}.csv")
    manifest = {**protocol, "completed_at_utc": datetime.now(timezone.utc), "selections": selections,
                "output_sha256": {str(p.relative_to(output)): file_hash(p) for p in sorted(output.rglob("*")) if p.is_file()}}
    save_json(manifest, output / "run_manifest.json")
    print(f"Completed: {output.resolve()}", flush=True)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("cache", "database"), default="cache")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "data" / "berka_prediction")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs" / "berka" / "inactivity_prediction" / datetime.now().strftime("%Y%m%d_%H%M%S"))
    parser.add_argument("--snapshot-freq", default="ME")
    parser.add_argument("--history-days", type=int, default=180)
    parser.add_argument("--min-transactions", type=int, default=1)
    parser.add_argument("--horizons", type=int, nargs="+", default=(90, 120, 180))
    parser.add_argument("--scopes", choices=SCOPES, nargs="+", default=SCOPES)
    parser.add_argument("--validation-start", default="1997-04-01")
    parser.add_argument("--test-start", default="1998-01-01")
    parser.add_argument("--seed", type=int, default=20260920)
    parser.add_argument("--bootstrap-repetitions", type=int, default=1000)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--no-stability", action="store_true")
    args = parser.parse_args()
    if min(args.history_days, args.min_transactions, args.bootstrap_repetitions, args.threads, *args.horizons) < 1:
        parser.error("History, count, horizons, repetitions and threads must be positive")
    config = Config(**{name: getattr(args, name) for name in Config.__dataclass_fields__ if name != "stability"},
                    stability=not args.no_stability)
    tables, provenance = load_tables(args.source, args.cache_dir, financial=True)
    run_analysis(tables, provenance, config, args.output_dir)


if __name__ == "__main__":
    main()
