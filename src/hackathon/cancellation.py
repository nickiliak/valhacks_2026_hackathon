"""CatBoost cancellation probabilities with frozen preprocessing and calibration."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from catboost import CatBoostClassifier
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

from hackathon.contracts import policy_inputs
from hackathon.preprocessing import (CATEGORICAL_FEATURES, FEATURE_COLUMNS, MODEL_CATEGORICAL,
                                     MODEL_FEATURES, FeatureBuilder, GroupCounter)
from hackathon.splits import Period, get_split, replay_population

EPSILON = 1e-7
ARTIFACT_VERSION = 2
_MODEL_COLUMNS = list(MODEL_FEATURES)
_MODEL_INDEX = [FEATURE_COLUMNS.index(c) for c in MODEL_FEATURES]


def probability_metrics(y, probability) -> dict:
    y = np.asarray(y, dtype=int)
    p = np.clip(np.asarray(probability, dtype=float), EPSILON, 1 - EPSILON)
    if not len(y):
        return {"rows": 0, "log_loss": None, "brier": None, "auc": None}
    return {"rows": len(y), "cancel_rate": float(y.mean()), "mean_p_cancel": float(p.mean()),
            "log_loss": float(log_loss(y, p, labels=[0, 1])),
            "brier": float(brier_score_loss(y, p)),
            "auc": float(roc_auc_score(y, p)) if len(np.unique(y)) > 1 else None}


@dataclass
class ProbabilityCalibration:
    method: str = "raw"
    parameters: dict | None = None

    @classmethod
    def fit(cls, method: str, probability, labels, *, rows=None):
        p = np.clip(np.asarray(probability), EPSILON, 1 - EPSILON)
        y = np.asarray(labels, dtype=int)
        if method == "raw":
            return cls()
        if len(np.unique(y)) < 2:
            raise ValueError("Calibration needs both cancellation outcomes")
        if method == "sigmoid":
            logits = np.log(p / (1 - p)).reshape(-1, 1)
            fit = LogisticRegression(C=1e6, solver="lbfgs", max_iter=1000).fit(logits, y)
            return cls(method, {"slope": float(fit.coef_[0, 0]), "intercept": float(fit.intercept_[0])})
        if method == "isotonic":
            fit = IsotonicRegression(out_of_bounds="clip").fit(p, y)
            return cls(method, {"x": fit.X_thresholds_.tolist(), "y": fit.y_thresholds_.tolist()})
        if method == "context":
            from hackathon.calibration import ContextCalibrator

            if rows is None:
                raise ValueError("Context calibration requires booking features")
            return cls(method, ContextCalibrator.fit(p, rows, y).parameters)
        raise ValueError(f"Unknown calibration method: {method}")

    def transform(self, probability, *, rows=None) -> np.ndarray:
        p = np.clip(np.asarray(probability, dtype=float), EPSILON, 1 - EPSILON)
        if self.method == "sigmoid":
            logits = self.parameters["slope"] * np.log(p / (1 - p)) + self.parameters["intercept"]
            p = 1 / (1 + np.exp(-np.clip(logits, -700, 700)))
        elif self.method == "isotonic":
            p = np.interp(p, self.parameters["x"], self.parameters["y"])
        elif self.method == "context":
            from hackathon.calibration import ContextCalibrator

            if rows is None:
                raise ValueError("Context calibration requires booking features")
            p = ContextCalibrator(self.parameters).transform(p, rows)
        elif self.method != "raw":
            raise ValueError(f"Unknown calibration method: {self.method}")
        return np.clip(p, EPSILON, 1 - EPSILON)

    def transform_one(self, probability: float, booking: dict) -> float:
        if self.method == "context":
            from hackathon.calibration import ContextCalibrator

            return ContextCalibrator(self.parameters).transform_one(probability, booking)
        return float(self.transform([probability])[0])


class CancellationModel:
    """Pass a fresh GroupCounter per replay; share it across all observed requests.

    p_cancel(batch) defaults to fresh state, suitable for an entire training or
    replay population. For online use score commitments with the same state used
    by p_cancel_one, including requests that the downstream policy rejects.
    """

    def __init__(self, features: FeatureBuilder, models: dict[str, CatBoostClassifier],
                 calibration: ProbabilityCalibration | None = None, metadata: dict | None = None):
        self.features = features
        self.models = models
        self.calibration = calibration or ProbabilityCalibration()
        self.metadata = metadata or {}

    def _raw(self, features: pd.DataFrame) -> np.ndarray:
        if features.empty:
            return np.empty(0)
        hotels = features.hotel.to_numpy()
        features = features[_MODEL_COLUMNS]
        if "all" in self.models:
            return self.models["all"].predict_proba(features, thread_count=1)[:, 1]
        probability = np.empty(len(features))
        for hotel in pd.unique(hotels):
            if hotel not in self.models:
                raise ValueError(f"No cancellation model for hotel {hotel!r}")
            positions = np.flatnonzero(hotels == hotel)
            probability[positions] = self.models[hotel].predict_proba(features.iloc[positions], thread_count=1)[:, 1]
        return probability

    def p_cancel(self, rows: pd.DataFrame, *, state: GroupCounter | None = None) -> np.ndarray:
        return self.calibration.transform(self._raw(self.features.make_features(rows, state=state)), rows=rows)

    def p_show(self, rows: pd.DataFrame, *, state: GroupCounter | None = None) -> np.ndarray:
        return 1 - self.p_cancel(rows, state=state)

    def p_cancel_one(self, booking: dict, *, state: GroupCounter) -> float:
        values = self.features.make_feature_row(booking, state)
        model = self.models.get("all")
        if model is None:
            model = self.models[str(booking["hotel"])]
        raw = model.predict_proba([[values[i] for i in _MODEL_INDEX]], thread_count=1)[0, 1]
        return self.calibration.transform_one(raw, booking)

    def save(self, directory: str | Path) -> None:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        files = {}
        checksums = {}
        for i, (name, model) in enumerate(sorted(self.models.items())):
            filename = f"model_{i}.cbm"
            model.save_model(str(directory / filename))
            files[name] = filename
            checksums[filename] = hashlib.sha256((directory / filename).read_bytes()).hexdigest()
        payload = {"version": ARTIFACT_VERSION, "feature_columns": list(FEATURE_COLUMNS),
                   "categorical_features": list(CATEGORICAL_FEATURES),
                   "model_features": _MODEL_COLUMNS,
                   "features": self.features.to_dict(), "models": files, "checksums": checksums,
                   "calibration": {"method": self.calibration.method, "parameters": self.calibration.parameters},
                   "metadata": self.metadata}
        (directory / "model.json").write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")

    @classmethod
    def load(cls, directory: str | Path):
        directory = Path(directory)
        payload = json.loads((directory / "model.json").read_text(encoding="utf-8"))
        if (payload["version"] != ARTIFACT_VERSION
                or payload["feature_columns"] != list(FEATURE_COLUMNS)
                or payload["categorical_features"] != list(CATEGORICAL_FEATURES)
                or payload.get("model_features") != _MODEL_COLUMNS):
            raise ValueError("Model artifact and feature schema versions do not match")
        models = {}
        for name, filename in payload["models"].items():
            path = directory / filename
            if hashlib.sha256(path.read_bytes()).hexdigest() != payload["checksums"][filename]:
                raise ValueError(f"Model checksum mismatch: {filename}")
            models[name] = CatBoostClassifier()
            models[name].load_model(str(path))
        return cls(FeatureBuilder.from_dict(payload["features"]), models,
                   ProbabilityCalibration(**payload["calibration"]), payload["metadata"])


def _fit_models(x, y, *, layout, iterations, depth, learning_rate, seed, threads,
                validation=None, selected_iterations=None):
    keys = ["all"] if layout == "combined" else sorted(x.hotel.unique())
    models = {}
    for key in keys:
        mask = np.ones(len(x), dtype=bool) if key == "all" else x.hotel.to_numpy() == key
        count = selected_iterations[key] if selected_iterations else iterations
        model = CatBoostClassifier(iterations=count, depth=depth, learning_rate=learning_rate,
                                   loss_function="Logloss", eval_metric="Logloss", random_seed=seed,
                                   thread_count=threads, cat_features=list(MODEL_CATEGORICAL),
                                   allow_writing_files=False, verbose=False)
        kwargs = {}
        if validation is not None:
            vx, vy = validation
            vmask = np.ones(len(vx), dtype=bool) if key == "all" else vx.hotel.to_numpy() == key
            if not vmask.any():
                raise ValueError(f"Internal validation contains no rows for {key}")
            kwargs = {"eval_set": (vx.loc[vmask, _MODEL_COLUMNS], vy[vmask]), "early_stopping_rounds": 75,
                      "use_best_model": True}
        if len(np.unique(y[mask])) < 2:
            raise ValueError(f"Training needs both outcomes for {key}")
        model.fit(x.loc[mask, _MODEL_COLUMNS], y[mask], **kwargs)
        models[key] = model
    return models


def train_cancellation_model(rows: pd.DataFrame, *, split_name="S2", layout="auto",
                             calibration="auto", iterations=800, depth=6, learning_rate=0.05,
                             seed=2026, threads=4, split=None) -> tuple[CancellationModel, dict]:
    """Select on internal validation, refit train, calibrate, then choose on tune.

    Confirmation rows never enter feature fitting, early stopping, calibration,
    calibration selection, or the returned report. Final/S1 require a calibration
    method frozen beforehand because neither defines an independent tune window.
    """
    # A custom ChronologicalSplit (rolling refits) overrides the named one.
    split = split or get_split(split_name)
    if calibration == "auto" and split.tuning is None:
        raise ValueError("S1/Final require an explicit calibration method frozen before this fit")
    if layout not in {"auto", "combined", "per_hotel"}:
        raise ValueError("layout must be auto, combined, or per_hotel")
    fit_rows, validation_rows = split.training_parts(rows)
    train_rows = split.train.select(rows)
    calibration_rows = split.calibration.select(rows)
    for name, frame in [("internal fit", fit_rows), ("internal validation", validation_rows),
                        ("training", train_rows), ("calibration", calibration_rows)]:
        if frame.empty:
            raise ValueError(f"No rows in {name} period for {split_name}")
    features = FeatureBuilder().fit(fit_rows)
    x_fit = features.make_features(fit_rows)
    x_validation = features.make_features(validation_rows)
    fit_y = fit_rows.cancelled.to_numpy(dtype=int)
    validation_y = validation_rows.cancelled.to_numpy(dtype=int)
    common = dict(iterations=iterations, depth=depth, learning_rate=learning_rate, seed=seed, threads=threads)
    trials = {}
    for candidate in (["combined", "per_hotel"] if layout == "auto" else [layout]):
        models = _fit_models(x_fit, fit_y, layout=candidate, validation=(x_validation, validation_y), **common)
        raw = CancellationModel(features, models)._raw(x_validation)
        trials[candidate] = {"metrics": probability_metrics(validation_y, raw),
                             "iterations": {key: model.tree_count_ for key, model in models.items()}}
    chosen_layout = min(trials, key=lambda name: trials[name]["metrics"]["log_loss"])
    # Refit only the training period, with the tree counts already frozen.
    features = FeatureBuilder().fit(train_rows)
    models = _fit_models(features.make_features(train_rows), train_rows.cancelled.to_numpy(dtype=int),
                         layout=chosen_layout, selected_iterations=trials[chosen_layout]["iterations"], **common)
    model = CancellationModel(features, models)
    cal_raw = model.p_cancel(calibration_rows)
    methods = ["raw", "sigmoid"] if calibration == "auto" else [calibration]
    if calibration == "auto" and len(calibration_rows) >= 2000:
        methods.append("isotonic")
    calibrators = {method: ProbabilityCalibration.fit(method, cal_raw, calibration_rows.cancelled,
                                                     rows=calibration_rows)
                   for method in methods}
    report = {"split": split.to_dict(), "seed": seed,
              "rows": {"internal_fit": len(fit_rows), "internal_validation": len(validation_rows),
                       "train": len(train_rows), "calibration": len(calibration_rows)},
              "model_selection": trials, "selected_layout": chosen_layout,
              "confirmation_evaluated": False, "calibration_candidates": {}}
    if split.tuning is not None:
        commitments, requests = replay_population(rows, split.tuning)
        population = pd.concat([commitments, requests])
        raw = model.p_cancel(population)
        if requests.empty:
            raise ValueError("No decision-like requests in the tuning period")
        request_raw = raw[len(commitments):]
        for method, calibrator in calibrators.items():
            report["calibration_candidates"][method] = probability_metrics(
                requests.cancelled, calibrator.transform(request_raw, rows=requests))
        chosen = min(calibrators, key=lambda method: report["calibration_candidates"][method]["log_loss"])
        model.calibration = calibrators[chosen]
        report["tuning"] = diagnostic_report(population, model.calibration.transform(raw, rows=population), split.tuning.start)
        report["calibration_selection_population"] = "Tuning requests booked on/after replay start; commitments excluded"
    else:
        model.calibration = calibrators[calibration]
        report["calibration_selection_population"] = "Explicit pre-frozen method; no holdout selection"
    report["selected_calibration"] = model.calibration.method
    report["feature_columns"] = _MODEL_COLUMNS
    model.metadata = report
    return model, report


def diagnostic_report(rows: pd.DataFrame, probability, replay_start: str) -> dict:
    p = np.asarray(probability)
    y = rows.cancelled.to_numpy(dtype=int)
    decisions = pd.to_datetime(rows.booking_date).to_numpy() >= np.datetime64(replay_start)
    output = {"all": probability_metrics(y, p), "requests": probability_metrics(y[decisions], p[decisions]),
              "lead_at_most_365": probability_metrics(y[rows.days_ahead <= 365], p[rows.days_ahead <= 365]),
              "by_hotel": {}, "by_lead_band": {}, "calibration_bins": {}}
    groups = {"all": np.ones(len(rows), dtype=bool)}
    for hotel in sorted(rows.hotel.unique()):
        mask = rows.hotel.to_numpy() == hotel
        output["by_hotel"][hotel] = probability_metrics(y[mask], p[mask])
        groups[hotel] = mask
    bounds = [(-1, 7), (7, 30), (30, 90), (90, 180), (180, 365), (365, np.inf)]
    for low, high in bounds:
        mask = ((rows.days_ahead > low) & (rows.days_ahead <= high)).to_numpy()
        name = f"{low + 1}-{high} days"
        output["by_lead_band"][name] = probability_metrics(y[mask], p[mask])
        groups[name] = mask
    groups["lead_at_most_365"] = (rows.days_ahead <= 365).to_numpy()
    for name, mask in groups.items():
        bins = np.minimum((p[mask] * 10).astype(int), 9)
        output["calibration_bins"][name] = [
            {"bin": int(b), "rows": int((bins == b).sum()),
             "mean_p_cancel": float(p[mask][bins == b].mean()),
             "cancel_rate": float(y[mask][bins == b].mean())}
            for b in np.unique(bins)]
    return output


def cache_replay_probabilities(rows: pd.DataFrame, period: Period,
                               output: str | Path, *, artifact_directory: str | Path) -> pd.DataFrame:
    """Recompute a scoped prediction cache; never reuse occupancy or stale scores."""
    # Loading here guarantees the fingerprint names the model actually used.
    model = CancellationModel.load(artifact_directory)
    commitments, requests = replay_population(rows, period)
    population = policy_inputs(pd.concat([commitments, requests]))
    probability = model.p_cancel(population)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    cached = population[["booking_id", "hotel", "booking_date", "arrival_date"]].copy()
    cached["role"] = ["commitment"] * len(commitments) + ["request"] * len(requests)
    cached["p_cancel"] = probability
    cached["p_show"] = 1 - probability
    cached.to_csv(output, index=False)
    digest = hashlib.sha256((Path(artifact_directory) / "model.json").read_bytes()).hexdigest()
    input_digest = hashlib.sha256(pd.util.hash_pandas_object(population, index=False).values.tobytes()).hexdigest()
    output.with_suffix(".manifest.json").write_text(json.dumps({
        "model_sha256": digest, "population_sha256": input_digest, "start": period.start,
        "end_exclusive": period.end, "rows": len(population), "group_state": "commitments then requests; all observed",
    }, indent=2), encoding="utf-8")
    return cached
