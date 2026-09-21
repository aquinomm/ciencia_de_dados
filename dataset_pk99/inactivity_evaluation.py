"""Purged splits, validation-only selection and account-cluster uncertainty."""

from dataclasses import dataclass
import warnings

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.exceptions import ConvergenceWarning
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler

from .inactivity_features import FEATURES

MODELS = ("prevalence", "recency", "logistic", "hist_gradient_boosting")
CI_METRICS = ("prevalence", "average_precision", "ap_lift", "roc_auc", "precision", "recall",
              "f1", "f2", "mcc", "balanced_accuracy", "brier")


def summarize(frame):
    return {"snapshots": len(frame), "accounts": frame.account_id.nunique(),
            "positives": int(frame.y.sum()), "prevalence": frame.y.mean(),
            "positive_accounts": frame.loc[frame.y.eq(1), "account_id"].nunique()}


def temporal_split(frame, validation_start, test_start, test_end=None, *, summarize_test=True):
    v, t = pd.Timestamp(validation_start), pd.Timestamp(test_start)
    if v >= t:
        raise ValueError("validation_start must precede test_start")
    train = (frame.snapshot_date < v) & (frame.label_end < v)
    val = (frame.snapshot_date >= v) & (frame.snapshot_date < t) & (frame.label_end < t)
    test = frame.snapshot_date >= t
    if test_end is not None:
        test &= frame.snapshot_date <= pd.Timestamp(test_end)
    masks = {"train": train, "validation": val, "test": test}
    splits = {name: frame.loc[mask].copy() for name, mask in masks.items()}
    if any(part.empty for part in splits.values()):
        raise ValueError("Empty temporal split; change calendar boundaries, not class labels")
    records = []
    for name, part in splits.items():
        next_start = v if name == "train" else t if name == "validation" else pd.NaT
        counts = summarize(part) if name != "test" or summarize_test else {}
        records.append({"split": name, **counts,
                        "snapshot_start": part.snapshot_date.min(), "snapshot_end": part.snapshot_date.max(),
                        "target_first_included_day": part.snapshot_date.min() + pd.Timedelta(days=1),
                        "target_last_included_day": part.label_end.max(), "next_period_start": next_start,
                        "snapshot_gap_days": (next_start - part.snapshot_date.max()).days if pd.notna(next_start) else None,
                        "label_gap_days": (next_start - part.label_end.max()).days if pd.notna(next_start) else None})
    purge = []
    for name, nominal, kept in (("before_validation", frame.snapshot_date < v, train),
                                ("before_test", (frame.snapshot_date >= v) & (frame.snapshot_date < t), val)):
        removed = frame.loc[nominal & ~kept]
        purge.append({"boundary": name, "snapshots": len(removed), "accounts": removed.account_id.nunique(),
                      "snapshot_start": removed.snapshot_date.min(), "snapshot_end": removed.snapshot_date.max()})
    return splits, records, purge


class MetricEvaluator:
    """Cached tied-score rankings; weights reproduce duplicated cluster rows exactly."""

    def __init__(self, y, score, threshold):
        self.y = np.asarray(y, dtype=int)
        self.score = np.asarray(score, dtype=float)
        if not np.isfinite(self.score).all() or ((self.score < 0) | (self.score > 1)).any():
            raise ValueError("Expected finite probabilities in [0,1]")
        self.pred = self.score >= threshold
        self.order = np.argsort(-self.score, kind="stable")
        sorted_score = self.score[self.order]
        self.ends = np.r_[np.flatnonzero(np.diff(sorted_score)), len(y) - 1]

    def compute(self, weights=None):
        y, pred = self.y, self.pred
        w = np.ones(len(y)) if weights is None else np.asarray(weights, dtype=float)
        pos, neg = np.sum(w * y), np.sum(w * (1-y))
        total = pos + neg
        tp, fp = np.sum(w * y * pred), np.sum(w * (1-y) * pred)
        fn, tn = pos-tp, neg-fp
        precision = tp / (tp+fp) if tp+fp else 0.
        recall = tp/pos if pos else np.nan
        f1 = 2*tp / (2*tp+fp+fn) if 2*tp+fp+fn else 0.
        f2 = 5*tp / (5*tp+fp+4*fn) if 5*tp+fp+4*fn else 0.
        denom = np.sqrt((tp+fp)*(tp+fn)*(tn+fp)*(tn+fn))
        ap = auc = np.nan
        if pos and neg:
            ranked_y, ranked_w = y[self.order], w[self.order]
            cum_tp = np.cumsum(ranked_w*ranked_y)[self.ends]
            cum_fp = np.cumsum(ranked_w*(1-ranked_y))[self.ends]
            precisions = np.divide(cum_tp, cum_tp+cum_fp, out=np.zeros_like(cum_tp), where=(cum_tp+cum_fp)>0)
            ap = np.sum(np.diff(np.r_[0., cum_tp/pos]) * precisions)
            auc = np.trapezoid(np.r_[0., cum_tp/pos], np.r_[0., cum_fp/neg])
        prevalence = pos/total if total else np.nan
        return {"prevalence": prevalence, "average_precision": ap,
                "ap_lift": ap/prevalence if pos else np.nan, "roc_auc": auc,
                "precision": precision, "recall": recall, "f1": f1, "f2": f2,
                "mcc": (tp*tn-fp*fn)/denom if denom else 0.,
                "balanced_accuracy": (recall+tn/neg)/2 if pos and neg else np.nan,
                "brier": np.sum(w*(self.score-y)**2)/total if total else np.nan,
                "tn": tn, "fp": fp, "fn": fn, "tp": tp,
                "mean_probability": np.sum(w*self.score)/total if total else np.nan}


def choose_threshold(y, probabilities):
    """Maximize validation F2; ties prefer the largest threshold."""
    y, p = np.asarray(y), np.asarray(probabilities)
    if not y.sum():
        return np.nextafter(1., 2.)
    order = np.argsort(-p, kind="stable")
    ends = np.r_[np.flatnonzero(np.diff(p[order])), len(y)-1]
    tp = np.cumsum(y[order])[ends]
    fp = ends+1-tp
    fn = y.sum()-tp
    f2 = 5*tp / (5*tp+fp+4*fn)
    return float(p[order][ends[np.argmax(f2)]])


def cluster_weights(account_ids, rng):
    accounts, inverse = np.unique(account_ids, return_inverse=True)
    multiplicities = np.bincount(rng.integers(0, len(accounts), len(accounts)), minlength=len(accounts))
    return multiplicities[inverse]


def clustered_bootstrap(frame, probabilities, threshold, repetitions=1000, seed=20260920):
    rng = np.random.default_rng(seed)
    evaluator = MetricEvaluator(frame.y, probabilities, threshold)
    accounts, inverse = np.unique(frame.account_id.to_numpy(), return_inverse=True)
    draws = pd.DataFrame([evaluator.compute(np.bincount(
        rng.integers(0, len(accounts), len(accounts)), minlength=len(accounts))[inverse])
        for _ in range(repetitions)])
    point = evaluator.compute()
    rows = []
    for metric in CI_METRICS:
        valid = draws[metric].dropna()
        rows.append({"metric": metric, "estimate": point[metric],
                     "ci_low": valid.quantile(.025) if len(valid) else np.nan,
                     "ci_high": valid.quantile(.975) if len(valid) else np.nan,
                     "valid_replicates": len(valid), "requested_replicates": repetitions,
                     "seed": seed, "cluster": "account_id", "method": "percentile"})
    return rows, draws


def model_matrix(frame, model):
    columns = {"recency": ["recency_days"], "frequency": ["count_30d"]}.get(model, list(FEATURES))
    assert all(not column.endswith("_id") for column in columns)
    return frame.loc[:, columns]


def make_estimator(name, params, seed):
    if name == "prevalence":
        return DummyClassifier(strategy="prior", random_state=seed)
    if name in ("recency", "frequency"):
        return make_pipeline(SimpleImputer(strategy="median", keep_empty_features=True),
                             FunctionTransformer(np.log1p),
                             LogisticRegression(C=1., max_iter=2000, random_state=seed))
    if name == "logistic":
        return make_pipeline(SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True),
                             StandardScaler(), LogisticRegression(max_iter=2000, random_state=seed, **params))
    return HistGradientBoostingClassifier(learning_rate=.05, max_iter=150, early_stopping=False,
                                          random_state=seed, **params)


def positive_probability(estimator, x):
    probabilities = estimator.predict_proba(x)
    classes = estimator.classes_
    return probabilities[:, list(classes).index(1)] if 1 in classes else np.zeros(len(x))


@dataclass
class SelectedModel:
    name: str
    estimator: object
    threshold: float
    params: dict
    validation_metrics: dict
    fallback: bool
    recency_cutoff_days: float | None = None

    def predict(self, frame):
        return positive_probability(self.estimator, model_matrix(frame, self.name))


def select_models(train, validation, seed=20260920, *, include_frequency=False):
    """No test argument: fit only train; select parameters/threshold only validation."""
    grids = {"prevalence": [{}], "recency": [{}], "logistic": [{"C": .1}, {"C": 1.}],
             "hist_gradient_boosting": [{"max_leaf_nodes": 7, "min_samples_leaf": 30, "l2_regularization": 10.},
                                        {"max_leaf_nodes": 15, "min_samples_leaf": 60, "l2_regularization": 30.}]}
    names = ("prevalence", "recency", "frequency", "logistic", "hist_gradient_boosting") if include_frequency else MODELS
    if include_frequency:
        grids["frequency"] = [{}]
    selected, candidates = {}, []
    fallback = train.y.nunique() < 2
    for name in names:
        ranked = []
        for index, params in enumerate(grids[name]):
            estimator = make_estimator("prevalence" if fallback else name, params, seed)
            with warnings.catch_warnings():
                warnings.simplefilter("error", ConvergenceWarning)
                estimator.fit(model_matrix(train, name), train.y)
            p = positive_probability(estimator, model_matrix(validation, name))
            threshold = choose_threshold(validation.y, p)
            metrics = MetricEvaluator(validation.y, p, threshold).compute()
            ap = metrics["average_precision"]
            rank = (ap if np.isfinite(ap) else -1., -metrics["brier"], -index)
            candidates.append({"model": name, "candidate": index, "params": params,
                               "single_class_train_fallback": fallback, "threshold": threshold, **metrics})
            cutoff = None
            if name == "recency" and not fallback:
                slope = estimator[-1].coef_[0, 0]
                if slope > 0 and 0 < threshold < 1:
                    cutoff = float(np.expm1((np.log(threshold/(1-threshold)) - estimator[-1].intercept_[0]) / slope))
            ranked.append((rank, SelectedModel(name, estimator, threshold, params, metrics, fallback, cutoff)))
        selected[name] = max(ranked, key=lambda item: item[0])[1]
    winner = max(names, key=lambda name: (
        selected[name].validation_metrics["average_precision"]
        if np.isfinite(selected[name].validation_metrics["average_precision"]) else -1.,
        -selected[name].validation_metrics["brier"], -names.index(name)))
    return selected, winner, candidates
