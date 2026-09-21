"""Prespecified active-to-inactive experiment on branch berka-temporal, CPU only."""

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess

import joblib
import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal
from threadpoolctl import threadpool_limits

from .activity_transition import (
    BASELINES, MODELS, assert_active, audit_split_integrity, build_active_dataset,
    episode_census, episode_summary, episode_tables, select_active_models,
)
from .data import file_hash, load_tables
from .eda import SCOPES, validate_tables
from .inactivity_features import FEATURES, activity_subset, build_features, validate_financial
from .inactivity_evaluation import MetricEvaluator, clustered_bootstrap, model_matrix, temporal_split
from .predict_inactivity import ROOT, model_record, plot_evaluation, save_csv, save_json


@dataclass(frozen=True)
class Config:
    snapshot_freq: str = "ME"
    history_days: int = 180
    active_windows: tuple[int, ...] = (30, 15, 60)
    horizons: tuple[int, ...] = (90, 120, 180)
    scopes: tuple[str, ...] = SCOPES
    validation_start: str = "1997-01-01"
    test_start: str = "1998-01-01"
    seed: int = 20260921
    bootstrap_repetitions: int = 1000
    threads: int = 4
    stability: bool = True


def require_branch():
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != "berka-temporal":
        raise RuntimeError(f"This experiment requires berka-temporal; current branch: {branch}")
    return branch


def summarize_splits(splits, key):
    counts, episodes, periods, crossings = [], [], [], []
    for split, frame in splits.items():
        counts.append({**key, "split": split, **episode_summary(frame)})
        ep, period, cross = episode_tables(frame, split)
        episodes.append(ep.assign(**key))
        periods.extend([{**key, **row} for row in period])
        crossings.append(cross.assign(**key))
    return counts, episodes, periods, crossings


def evaluate_models(frame, models, winner, key, *, train=None):
    rows, predictions = [], []
    for name in MODELS:
        context = {**key, "model": name, "selected_on_validation": name == winner,
                   "fit_status": "fitted" if name in models else "unavailable_single_class_train",
                   **episode_summary(frame)}
        if train is not None:
            context.update({f"train_{k}": v for k, v in episode_summary(train).items()})
        if name not in models:
            rows.append(context)
            continue
        model = models[name]
        p = model.predict(frame)
        rows.append({**context, "threshold": model.threshold, **MetricEvaluator(frame.y, p, model.threshold).compute()})
        predictions.append(frame[["account_id", "snapshot_date", "label_end", "y", "recency_days",
                                  "episode_id", "silence_H_day"]].assign(
            **key, model=name, probability=p, predicted=(p >= model.threshold).astype(int)))
    return rows, predictions


def expanding_windows(dataset, key, config):
    rows, counts, definitions, choices, audits, predictions = [], [], [], [], [], []
    final = pd.Timestamp(config.test_start)
    for window, months in ((1, 12), (2, 9)):
        test_start = final - pd.DateOffset(months=months)
        test_end = test_start + pd.DateOffset(months=3) - pd.Timedelta(days=1)
        validation_start = test_start - pd.DateOffset(months=9)
        development = dataset.loc[(dataset.snapshot_date <= test_end) & (dataset.label_end < final)]
        splits, defs, _ = temporal_split(development, validation_start, test_start, test_end)
        window_key = {**key, "window": window}
        audits.append({**window_key, **audit_split_integrity(splits, key["active_days"], validation_start, test_start)})
        models, winner, candidates = select_active_models(splits["train"], splits["validation"], key["active_days"], config.seed)
        choices.append({**window_key, "winner": winner, "candidates": candidates,
                        "available_models": list(models), "selection": {n: model_record(m) for n, m in models.items()}})
        result, pred = evaluate_models(splits["test"], models, winner, window_key, train=splits["train"])
        rows.extend(result)
        predictions.extend(pred)
        definitions.extend([{**window_key, **d} for d in defs])
        counts.extend(summarize_splits(splits, window_key)[0])
    return rows, counts, definitions, choices, audits, predictions


def real_data_audit(accounts, transactions, datasets, config):
    rng = np.random.default_rng(config.seed)
    positive_ids = set()
    for dataset in datasets.values():
        positive_ids.update(dataset.loc[dataset.y.eq(1), "account_id"])
    ids = set(rng.choice(accounts.account_id, min(30, len(accounts)), replace=False)) | positive_ids
    selected_accounts = accounts.loc[accounts.account_id.isin(ids)]
    selected_transactions = transactions.loc[transactions.account_id.isin(ids)]
    dates = [pd.Timestamp(config.validation_start) - pd.Timedelta(days=1),
             pd.Timestamp(config.test_start) - pd.Timedelta(days=1),
             pd.Timestamp(config.test_start) + pd.offsets.MonthEnd(6)]
    checks = []
    for scope in config.scopes:
        for date in dates:
            original = build_features(selected_accounts, selected_transactions, pd.DatetimeIndex([date]), transactions.trans_date.min(), scope)
            past = selected_transactions.loc[selected_transactions.trans_date.le(date)]
            truncated = build_features(selected_accounts, past, pd.DatetimeIndex([date]), transactions.trans_date.min(), scope)
            assert_frame_equal(original, truncated)
            for active_days in config.active_windows:
                assert_frame_equal(original.loc[original.recency_days.le(active_days)],
                                   truncated.loc[truncated.recency_days.le(active_days)])
            checks.append({"scope": scope, "date": date, "accounts": len(selected_accounts),
                           "future_feature_invariance": True, "future_eligibility_invariance": True})
    for name, dataset in datasets.items():
        scope = name.rsplit("_a", 1)[0]
        # Sample negatives as well as every positive, without affecting model selection.
        sample = pd.concat([dataset.loc[dataset.y.eq(1)], dataset.loc[dataset.y.eq(0)].sample(
            n=min(40, int(dataset.y.eq(0).sum())), random_state=config.seed)])
        events = activity_subset(transactions, scope)
        groups = {a: np.sort(g.trans_date.to_numpy(dtype="datetime64[ns]")) for a, g in events.groupby("account_id")}
        for row in sample.itertuples():
            dates_array = groups[row.account_id]
            observed = ((dates_array > row.snapshot_date.to_datetime64()) & (dates_array <= row.label_end.to_datetime64())).sum()
            assert row.y == int(observed == 0)
        checks.append({"experiment": name, "target_rows_checked": len(sample), "target_interval_direct_check": True})
    return checks


def run_analysis(tables, provenance, config, output, previous_run=None):
    branch = require_branch()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty output directory")
    output.mkdir(parents=True, exist_ok=True)
    accounts, transactions, quality = validate_tables(tables)
    transactions = validate_financial(transactions)
    start, end = transactions.trans_date.min(), transactions.trans_date.max()
    dates = pd.date_range(start, end, freq=config.snapshot_freq)
    source_files = [*sorted((ROOT / "dataset_pk99").glob("*.py")), *sorted((ROOT / "tests").glob("*.py")), ROOT / "requirements.txt"]
    protocol = {"experiment": "active_to_future_inactivity_v1", "created_at_utc": datetime.now(timezone.utc),
                "branch": branch, "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "config": asdict(config), "primary": {"active_days": 30, "horizon": 90},
                "features": FEATURES, "data_quality": quality, "data_provenance": provenance,
                "snapshot_dates": dates.tolist(), "source_sha256": {str(p.relative_to(ROOT)): file_hash(p) for p in source_files},
                "target": "recency(T)<=A then zero qualifying events in (T,T+H]",
                "episode_key": "account_id + last qualifying activity date known at T",
                "episode_independence_assumed": False,
                "population_filter_stage": "before target construction and all splits/model fits",
                "selection": "validation AP, tie lower Brier, tie fixed candidate order",
                "threshold": "validation maximum F2, tie largest threshold; no validation positives -> predict none",
                "refit_train_validation": False, "class_rebalancing": None,
                "unavailable_model_rule": "single-class train: only prevalence; other families marked unavailable",
                "single_class_validation_rule": "select prevalence; no AP-based family selection is identifiable",
                "bootstrap": {"unit": "account_id", "seed": config.seed, "replicates": config.bootstrap_repetitions,
                              "method": "unstratified percentile 95%, conditional on frozen fit/selection"},
                "python": platform.python_version(), "packages": {n: importlib.metadata.version(n) for n in
                    ("numpy", "pandas", "scikit-learn", "scipy", "joblib", "matplotlib", "threadpoolctl", "mysql-connector-python")}}
    save_json(protocol, output / "protocol.json")
    datasets, experiments = {}, {}
    eligibility, populations, counts, episodes, periods, crossings, definitions, purges, audits = [], [], [], [], [], [], [], [], []
    with threadpool_limits(limits=config.threads):
        for scope in config.scopes:
            require_branch()
            print(f"Building past-only features: {scope}", flush=True)
            features = build_features(accounts, transactions, dates, start, scope)
            for active_days in config.active_windows:
                # Export eligible feature rows only; the population is not a TEST diagnostic filter.
                save_csv(features.loc[features.recency_days.le(active_days) & features.observed_history_days.ge(config.history_days)],
                         output / f"features_{scope}_a{active_days}.csv.gz")
                for horizon in config.horizons:
                    key = {"scope": scope, "active_days": active_days, "horizon": horizon}
                    name = f"{scope}_a{active_days}_h{horizon}"
                    directory = output / name
                    directory.mkdir()
                    dataset, funnel = build_active_dataset(features, transactions, scope, horizon, end, active_days, config.history_days)
                    datasets[name] = dataset
                    splits, defs, purge = temporal_split(dataset, config.validation_start, config.test_start)
                    audits.append({**key, **audit_split_integrity(splits, active_days, config.validation_start, config.test_start)})
                    eligibility.append({**key, **funnel})
                    definitions.extend([{**key, **d} for d in defs])
                    purges.extend([{**key, **d} for d in purge])
                    c, ep, per, cross = summarize_splits(splits, key)
                    counts.extend(c); episodes.extend(ep); periods.extend(per); crossings.extend(cross)
                    census = episode_census(accounts, transactions, dates, scope, horizon, active_days, config.history_days, start, end)
                    captured = census.loc[census.captured_by_calendar]
                    assert set(captured.episode_id) == set(dataset.loc[dataset.y.eq(1), "episode_id"])
                    assert int(captured.calendar_positive_snapshots.sum()) == int(dataset.y.sum())
                    populations.append({**key, "population": "all_complete_before_purge", **episode_summary(dataset),
                                        "possible_daily_episodes": len(census), "possible_daily_positive_accounts": census.account_id.nunique(),
                                        "episodes_missed_by_monthly_calendar": int((~census.captured_by_calendar).sum())})
                    populations.append({**key, "population": "used_splits", **episode_summary(pd.concat(splits.values()))})
                    save_csv(census, directory / "episode_census.csv")
                    save_csv(dataset.drop(columns=list(FEATURES)), directory / "cohort_labels.csv.gz")
                    experiments[name] = (key, splits, directory)
        # Event counts are finalized before any model fitting/performance interpretation.
        for filename, frame in (("eligibility", pd.DataFrame(eligibility)), ("population_audit", pd.DataFrame(populations)),
                                 ("split_event_counts", pd.DataFrame(counts)), ("splits", pd.DataFrame(definitions)),
                                 ("purges", pd.DataFrame(purges)), ("episodes", pd.concat(episodes)),
                                 ("snapshot_period_events", pd.DataFrame(periods)), ("event_crossing_periods", pd.concat(crossings))):
            save_csv(frame, output / f"{filename}.csv")
        save_json(audits, output / "split_leakage_audit.json")
        print("Event audit saved. Starting active-population model selection.", flush=True)
        fitted, frozen, candidates, validation_metrics = {}, {}, [], []
        stability_rows, stability_counts, stability_defs, stability_choices, stability_audits, stability_pred = [], [], [], [], [], []
        for name, (key, splits, directory) in experiments.items():
            print(f"TRAIN/VALIDATION: {name}", flush=True)
            models, winner, search = select_active_models(splits["train"], splits["validation"], key["active_days"], config.seed)
            fitted[name] = (models, winner)
            candidates.extend([{**key, **row} for row in search])
            record = {"winner": winner, "available_models": list(models), "models": {n: model_record(m) for n, m in models.items()}}
            save_json(record, directory / "selection.json")
            joblib.dump(models, directory / "fitted_models.joblib")
            frozen[name] = {"winner": winner, "available_models": list(models),
                            "selection_sha256": file_hash(directory / "selection.json"),
                            "models_sha256": file_hash(directory / "fitted_models.joblib")}
            val_rows, val_predictions = evaluate_models(splits["validation"], models, winner, key)
            validation_metrics.extend(val_rows)
            save_csv(pd.concat(val_predictions), directory / "validation_predictions.csv.gz")
            if config.stability and key["active_days"] == 30:
                r, c, d, choices, a, pred = expanding_windows(datasets[name], key, config)
                stability_rows.extend(r); stability_counts.extend(c); stability_defs.extend(d)
                stability_choices.extend(choices); stability_audits.extend(a); stability_pred.extend(pred)
        save_json(candidates, output / "validation_candidates.json")
        save_csv(pd.DataFrame(validation_metrics), output / "validation_metrics.csv")
        if config.stability:
            save_csv(pd.DataFrame(stability_rows), output / "stability_metrics.csv")
            save_csv(pd.DataFrame(stability_counts), output / "stability_event_counts.csv")
            save_csv(pd.DataFrame(stability_defs), output / "stability_splits.csv")
            save_json(stability_choices, output / "stability_selections.json")
            save_json(stability_audits, output / "stability_leakage_audit.json")
            save_csv(pd.concat(stability_pred), output / "stability_predictions.csv.gz")
        save_json({"frozen_at_utc": datetime.now(timezone.utc), "protocol_sha256": file_hash(output / "protocol.json"),
                   "experiments": frozen}, output / "frozen_selection.json")
        print("All selections frozen. Opening final TEST.", flush=True)
        metrics, intervals, paired, monthly, common_calendar, episode_detection, replay = [], [], [], [], [], [], []
        for name, (key, splits, directory) in experiments.items():
            print(f"TEST/bootstrap: {name}", flush=True)
            models, winner = fitted[name]
            test = splits["test"]
            rows, predictions = evaluate_models(test, models, winner, key, train=splits["train"])
            metrics.extend(rows)
            save_csv(pd.concat(predictions), directory / "test_predictions.csv.gz")
            draws, scores = {}, {}
            for model_name, model in models.items():
                p = model.predict(test)
                scores[model_name] = p
                ci, draw = clustered_bootstrap(test, p, model.threshold, config.bootstrap_repetitions, config.seed)
                intervals.extend([{**key, "model": model_name, **row} for row in ci])
                draws[model_name] = draw
                positive = test.loc[test.y.eq(1)].copy()
                positive["detected"] = (p[test.y.eq(1)] >= model.threshold)
                detected = positive.groupby("episode_id").detected.max()
                episode_detection.append({**key, "model": model_name, "positive_episodes": len(detected),
                                          "episodes_detected_at_least_once": int(detected.sum()),
                                          "episode_recall": detected.mean()})
                for date, part in test.groupby("snapshot_date"):
                    mask = test.snapshot_date.eq(date)
                    monthly.append({**key, "model": model_name, "snapshot_date": date, **episode_summary(part),
                                    **MetricEvaluator(part.y, p[mask], model.threshold).compute()})
                mask = test.snapshot_date.le(end - pd.Timedelta(days=max(config.horizons)))
                if mask.any():
                    common_calendar.append({**key, "model": model_name, **episode_summary(test.loc[mask]),
                                            **MetricEvaluator(test.loc[mask, "y"], p[mask], model.threshold).compute()})
            for model_name in models:
                for baseline in BASELINES:
                    if baseline not in models or baseline == model_name:
                        continue
                    for metric in ("average_precision", "brier"):
                        delta = draws[model_name][metric] - draws[baseline][metric]
                        point = next(r for r in rows if r["model"] == model_name)[metric] - next(r for r in rows if r["model"] == baseline)[metric]
                        paired.append({**key, "model": model_name, "baseline": baseline, "metric": metric,
                                       "difference": point, "ci_low": delta.quantile(.025), "ci_high": delta.quantile(.975),
                                       "valid_replicates": delta.notna().sum()})
            save_csv(pd.concat([d.assign(model=n, replicate=np.arange(len(d))) for n, d in draws.items()]), directory / "bootstrap_draws.csv.gz")
            plot_evaluation(test, scores, directory)
            restored = joblib.load(directory / "fitted_models.joblib")
            for model_name, model in restored.items():
                expected = list(model_matrix(test, model_name).columns)
                assert list(model.estimator.feature_names_in_) == expected
                np.testing.assert_allclose(model.predict(test), scores[model_name], rtol=1e-12, atol=1e-12)
            replay.append({**key, "model_hash_verified": file_hash(directory / "fitted_models.joblib") == frozen[name]["models_sha256"],
                           "predictions_replayed": True, "all_model_feature_names_verified": True})
        for filename, rows in (("test_metrics", metrics), ("test_confidence_intervals", intervals),
                               ("paired_baseline_differences", paired), ("test_monthly_metrics", monthly),
                               ("common_calendar_metrics", common_calendar), ("episode_detection", episode_detection)):
            save_csv(pd.DataFrame(rows), output / f"{filename}.csv")
        save_json(replay, output / "model_replay_audit.json")
        save_json(real_data_audit(accounts, transactions, datasets, config), output / "real_data_leakage_audit.json")
        if previous_run is not None:
            old = pd.read_csv(previous_run / "test_metrics.csv")
            old["experiment"] = "previous_general_population"
            current = pd.DataFrame(metrics).loc[lambda d: d.active_days.eq(30)].copy()
            current["experiment"] = "new_active_population_trained_from_scratch"
            columns = ["experiment", "scope", "horizon", "model", "snapshots", "positives", "positive_accounts",
                       "prevalence", "average_precision", "roc_auc", "brier"]
            save_csv(pd.concat([old[columns], current[columns]]), output / "previous_experiment_diagnostic.csv")
    require_branch()
    manifest = {**protocol, "completed_at_utc": datetime.now(timezone.utc), "selections": frozen,
                "previous_run_diagnostic_sha256": file_hash(previous_run / "test_metrics.csv") if previous_run else None,
                "output_sha256": {str(p.relative_to(output)): file_hash(p) for p in sorted(output.rglob("*")) if p.is_file()}}
    save_json(manifest, output / "run_manifest.json")
    print(f"Completed: {output.resolve()}", flush=True)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("cache", "database"), default="cache")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "data" / "berka_prediction")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs" / "berka" / "activity_transition" / datetime.now().strftime("%Y%m%d_%H%M%S"))
    parser.add_argument("--previous-run", type=Path)
    parser.add_argument("--snapshot-freq", default="ME")
    parser.add_argument("--history-days", type=int, default=180)
    parser.add_argument("--active-windows", nargs="+", type=int, default=(30, 15, 60))
    parser.add_argument("--horizons", nargs="+", type=int, default=(90, 120, 180))
    parser.add_argument("--scopes", nargs="+", choices=SCOPES, default=SCOPES)
    parser.add_argument("--validation-start", default="1997-01-01")
    parser.add_argument("--test-start", default="1998-01-01")
    parser.add_argument("--seed", type=int, default=20260921)
    parser.add_argument("--bootstrap-repetitions", type=int, default=1000)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--no-stability", action="store_true")
    args = parser.parse_args()
    if min(args.history_days, args.bootstrap_repetitions, args.threads, *args.active_windows, *args.horizons) < 1:
        parser.error("All integer settings must be positive")
    if max(args.active_windows) >= min(args.horizons):
        parser.error("Active eligibility windows must be shorter than every future horizon")
    if args.no_stability is False and 30 not in args.active_windows:
        parser.error("Include principal active window 30 or explicitly disable stability")
    require_branch()
    config = Config(**{n: getattr(args, n) for n in Config.__dataclass_fields__ if n != "stability"}, stability=not args.no_stability)
    tables, provenance = load_tables(args.source, args.cache_dir, financial=True)
    run_analysis(tables, provenance, config, args.output_dir, args.previous_run)


if __name__ == "__main__":
    main()
