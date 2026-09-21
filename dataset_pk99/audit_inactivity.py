"""Audit a frozen run without training, selection or threshold changes."""

import argparse
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal
from threadpoolctl import threadpool_limits

from .data import file_hash, load_tables
from .eda import validate_tables
from .inactivity_features import FEATURES, build_features, make_dataset, activity_subset, validate_financial
from .inactivity_evaluation import clustered_bootstrap
from .predict_inactivity import ROOT, plot_evaluation, save_csv, save_json
import json


def audit_run(output, cache):
    manifest = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
    frozen = json.loads((output / "frozen_selection.json").read_text(encoding="utf-8"))
    for name, expected in frozen["experiments"].items():
        for artifact in ("selection", "fitted_models"):
            path = output / name / ("selection.json" if artifact == "selection" else "fitted_models.joblib")
            assert file_hash(path) == expected[f"{artifact}_sha256"]
    tables, provenance = load_tables("cache", cache, financial=True)
    assert provenance["sha256"] == manifest["data_provenance"]["sha256"]
    accounts, trans, _ = validate_tables(tables)
    trans = validate_financial(trans)
    seed = manifest["config"]["seed"]
    rng = np.random.default_rng(seed)
    ids = rng.choice(accounts.account_id, 30, replace=False)
    # Include every positive TEST account, in addition to the fixed random sample.
    positive_ids = []
    for name in frozen["experiments"]:
        p = pd.read_csv(output / name / "test_predictions.csv.gz")
        positive_ids.extend(p.loc[p.y.eq(1), "account_id"].unique())
    ids = np.unique(np.r_[ids, positive_ids])
    a, t = accounts.loc[accounts.account_id.isin(ids)], trans.loc[trans.account_id.isin(ids)]
    checks = []
    for scope in manifest["config"]["scopes"]:
        for date in ("1996-12-31", "1997-06-30", "1998-06-30"):
            dates = pd.DatetimeIndex([date])
            f = build_features(a, t, dates, trans.trans_date.min(), scope)
            truncated = build_features(a, t.loc[t.trans_date.le(date)], dates, trans.trans_date.min(), scope)
            assert_frame_equal(f, truncated)
            for horizon in manifest["config"]["horizons"]:
                d, _ = make_dataset(f, t, scope, horizon, trans.trans_date.max(),
                                    manifest["config"]["history_days"], manifest["config"]["min_transactions"])
                events = activity_subset(t, scope)
                for row in d.itertuples():
                    future = events.loc[events.account_id.eq(row.account_id) & events.trans_date.gt(row.snapshot_date)
                                        & events.trans_date.le(row.label_end)]
                    assert row.y == int(future.empty)
                checks.append({"scope": scope, "T": date, "horizon": horizon, "accounts_checked": len(d),
                               "future_invariance": True, "target_bruteforce": True})
    intervals, paired, concentration = [], [], []
    feature_cache = {}
    for name in frozen["experiments"]:
        directory = output / name
        models = joblib.load(directory / "fitted_models.joblib")
        for model in models.values():
            expected = ["recency_days"] if model.name == "recency" else list(FEATURES)
            assert list(model.estimator.feature_names_in_) == expected
        p = pd.read_csv(directory / "test_predictions.csv.gz", parse_dates=["snapshot_date", "label_end"],
                        float_precision="round_trip")
        reference = p.loc[p.model.eq("recency")]
        scope = name.rsplit("_h", 1)[0]
        if scope not in feature_cache:
            feature_cache[scope] = pd.read_csv(output / f"features_{scope}.csv.gz", parse_dates=["snapshot_date"],
                                               float_precision="round_trip")
        replay = reference[["account_id", "snapshot_date"]].merge(
            feature_cache[scope], on=["account_id", "snapshot_date"], validate="one_to_one", sort=False)
        for model_name, model in models.items():
            np.testing.assert_allclose(model.predict(replay), p.loc[p.model.eq(model_name), "probability"],
                                       rtol=1e-10, atol=1e-12)
        key = {"experiment": name}
        counts = reference.loc[reference.y.eq(1)].groupby("account_id").size().sort_values(ascending=False)
        concentration.append({**key, "positive_accounts": len(counts), "positive_snapshots": counts.sum(),
                              "top_5_account_positive_snapshots": counts.head(5).sum(),
                              "max_positive_snapshots_one_account": counts.max()})
        for model in ("recency", "hist_gradient_boosting"):
            recent = p.loc[p.model.eq(model) & p.recency_days.le(30)]
            ci, _ = clustered_bootstrap(recent, recent.probability, models[model].threshold,
                                       manifest["config"]["bootstrap_repetitions"], seed)
            intervals.extend([{**key, "model": model, "cohort": "recent_activity_30d", **row} for row in ci])
        draws = pd.read_csv(directory / "bootstrap_draws.csv.gz")
        baseline = draws.loc[draws.model.eq("recency")].set_index("replicate")
        for model in ("logistic", "hist_gradient_boosting"):
            for metric in ("average_precision", "brier"):
                other = draws.loc[draws.model.eq(model)].set_index("replicate")
                diff = other[metric] - baseline[metric]
                paired.append({**key, "model": model, "baseline": "recency", "metric": metric,
                               "ci_low": diff.quantile(.025), "ci_high": diff.quantile(.975),
                               "valid_replicates": diff.notna().sum()})
        scores = {model: p.loc[p.model.eq(model), "probability"].to_numpy() for model in models}
        plot_evaluation(reference, scores, directory)
    for name, rows in (("real_data_leakage_audit", checks), ("recent_activity_confidence_intervals", intervals),
                       ("model_vs_recency_paired_intervals", paired), ("positive_concentration", concentration)):
        save_csv(pd.DataFrame(rows), output / f"{name}.csv")
    changed_sources = {str(p.relative_to(ROOT)): file_hash(p) for p in sorted((ROOT / "dataset_pk99").glob("*.py"))}
    manifest["postprocessing_audit"] = {"completed_at_utc": datetime.now(timezone.utc), "source_sha256": changed_sources,
                                       "seed": seed, "accounts_checked": len(ids),
                                       "frozen_models_and_selections_verified": True,
                                       "saved_predictions_replayed": True,
                                       "pr_rendering": "step plot; metrics and predictions unchanged",
                                       "scope": "diagnostic only; no refitting or threshold selection"}
    manifest["output_sha256"] = {str(p.relative_to(output)): file_hash(p) for p in sorted(output.rglob("*"))
                                  if p.is_file() and p.name != "run_manifest.json"}
    save_json(manifest, output / "run_manifest.json")
    print(f"Audit passed: {len(ids)} accounts; {len(checks)} scope/date/horizon checks", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "data" / "berka_prediction")
    args = parser.parse_args()
    with threadpool_limits(limits=4):
        audit_run(args.output_dir, args.cache_dir)


if __name__ == "__main__":
    main()
