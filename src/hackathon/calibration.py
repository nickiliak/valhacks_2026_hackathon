"""Regularized cancellation calibration using booking context available at decision time.

Fit only on the supplied calibration rows and labels. The fitted parameters are
JSON-serializable and contain no live booking state or underlying tree model.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import math

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression


_MISSING = "_MISSING_"
_CATEGORY_NAMES = ("hotel", "lead_band", "hotel_lead", "hotel_segment", "guest_type", "hotel_agent")
_LEAD_BANDS = ((7, "0-7"), (30, "8-30"), (90, "31-90"), (180, "91-180"), (365, "181-365"))
_LEAD_SCALE = math.log(366)


def _category(value) -> str:
    return _MISSING if value is None or pd.isna(value) else str(value)


def _agent(value) -> str:
    # Keep the prototype's missing-agent level and normalize integer-like IDs.
    if value is None or pd.isna(value):
        return "-1"
    text = str(value).strip()
    try:
        number = Decimal(text)
    except InvalidOperation:
        return text
    return format(number.normalize(), "f") if number.is_finite() else "-1"


def _context(booking: Mapping) -> tuple[float, dict[str, str]]:
    try:
        ahead = float(booking.get("days_ahead", 0))
        ahead = max(ahead, 0.0) if math.isfinite(ahead) else 0.0
    except (TypeError, ValueError):
        ahead = 0.0
    hotel = _category(booking.get("hotel"))
    band = next((label for bound, label in _LEAD_BANDS if ahead <= bound), "366+")
    return ahead, {
        "hotel": hotel,
        "lead_band": band,
        "hotel_lead": hotel + "|" + band,
        "hotel_segment": hotel + "|" + _category(booking.get("sales_segment")),
        "guest_type": _category(booking.get("guest_type")),
        "hotel_agent": hotel + "|" + _agent(booking.get("agent")),
    }


def _records(rows) -> list[Mapping]:
    if isinstance(rows, pd.DataFrame):
        return rows.to_dict(orient="records")
    return [rows] if isinstance(rows, Mapping) else list(rows)


def _probabilities(raw, count: int) -> np.ndarray:
    probabilities = np.asarray(raw, dtype=float)
    if probabilities.ndim == 0:
        probabilities = probabilities.reshape(1)
    if probabilities.ndim != 1 or len(probabilities) != count:
        raise ValueError("Raw probabilities and booking rows must have matching one-dimensional lengths")
    if np.isnan(probabilities).any():
        raise ValueError("Raw probabilities must not contain missing values")
    return np.clip(probabilities, 1e-6, 1 - 1e-6)


def _design(raw, records, categories, order) -> np.ndarray:
    p = _probabilities(raw, len(records))
    contexts = [_context(row) for row in records]
    logits = np.log(p / (1 - p)) / 4.0
    seaside = np.array([values["hotel"] == "Seaside Hotel" for _, values in contexts], dtype=float)
    lead = np.log1p(np.array([ahead for ahead, _ in contexts], dtype=float)) / _LEAD_SCALE
    columns = [np.column_stack((logits, logits * seaside, lead, lead * seaside))]
    for name in order:
        values = np.array([values[name] for _, values in contexts], dtype=object)
        columns.extend((values == level).astype(float).reshape(-1, 1) for level in categories[name])
    return np.concatenate(columns, axis=1)


@dataclass
class ContextCalibrator:
    """Calibrate raw cancellation probabilities with a small logistic model.

    Unknown categories contribute no category-specific adjustment. Missing
    booking fields use the same defaults in batch and single-booking scoring.
    Reconstruct from ``ContextCalibrator(json.loads(saved_parameters))``.
    """

    parameters: dict

    def __post_init__(self) -> None:
        if self.parameters.get("version", 1) != 1:
            raise ValueError("Unsupported contextual calibration version")
        self._categories = self.parameters["categories"]
        self._order = self.parameters.get("category_order", list(self._categories))
        if (len(set(self._order)) != len(self._order)
                or set(self._order) != set(self._categories)
                or not set(self._order).issubset(_CATEGORY_NAMES)):
            raise ValueError("Unsupported contextual calibration categories")
        self._coefficient = np.asarray(self.parameters["coefficient"], dtype=float)
        self._intercept = float(self.parameters["intercept"])
        width = 4 + sum(len(self._categories[name]) for name in self._order)
        if (self._coefficient.shape != (width,) or not np.isfinite(self._coefficient).all()
                or not math.isfinite(self._intercept)):
            raise ValueError("Invalid contextual calibration coefficients")
        self._weights = {}
        position = 4
        for name in self._order:
            levels = self._categories[name]
            if len(set(levels)) != len(levels):
                raise ValueError("Duplicate contextual calibration category levels")
            self._weights[name] = dict(zip(levels, self._coefficient[position:position + len(levels)]))
            position += len(levels)

    @classmethod
    def fit(cls, raw, rows, labels, *, C=1.0, agents=True, minimum_count=100):
        records = _records(rows)
        y = np.asarray(labels, dtype=float)
        if y.ndim != 1 or len(y) != len(records) or not len(y):
            raise ValueError("Calibration requires nonempty booking rows and matching labels")
        if not np.isin(y, [0, 1]).all() or len(np.unique(y)) != 2:
            raise ValueError("Calibration requires both binary cancellation outcomes")
        if not math.isfinite(C) or C <= 0 or minimum_count < 1 or int(minimum_count) != minimum_count:
            raise ValueError("C and minimum_count must be positive; minimum_count must be an integer")
        contexts = [_context(row)[1] for row in records]
        names = list(_CATEGORY_NAMES if agents else _CATEGORY_NAMES[:-1])
        levels = {}
        for name in names:
            counts = Counter(values[name] for values in contexts)
            minimum = minimum_count if name == "hotel_agent" else 30
            levels[name] = sorted(level for level, count in counts.items() if count >= minimum)
        fitted = LogisticRegression(C=C, max_iter=2000, solver="lbfgs").fit(
            _design(raw, records, levels, names), y.astype(int),
        )
        return cls({
            "version": 1, "categories": levels, "category_order": names,
            "C": float(C), "agents": bool(agents), "minimum_count": int(minimum_count),
            "coefficient": fitted.coef_[0].tolist(), "intercept": float(fitted.intercept_[0]),
            "fit_rows": len(records), "iterations": int(fitted.n_iter_[0]),
        })

    def design(self, raw, rows) -> np.ndarray:
        return _design(raw, _records(rows), self._categories, self._order)

    def transform(self, raw, rows) -> np.ndarray:
        z = self.design(raw, rows) @ self._coefficient + self._intercept
        return np.clip(1 / (1 + np.exp(-np.clip(z, -30, 30))), 1e-7, 1 - 1e-7)

    def transform_one(self, raw, booking: Mapping) -> float:
        """Score one request without building a DataFrame or design matrix."""
        p = float(raw)
        if math.isnan(p):
            raise ValueError("Raw probabilities must not contain missing values")
        p = min(max(p, 1e-6), 1 - 1e-6)
        ahead, categories = _context(booking)
        seaside = float(categories["hotel"] == "Seaside Hotel")
        logit = math.log(p / (1 - p)) / 4.0
        lead = math.log1p(ahead) / _LEAD_SCALE
        z = self._intercept + sum(weight * value for weight, value in zip(
            self._coefficient[:4], (logit, logit * seaside, lead, lead * seaside),
        ))
        for name, weights in self._weights.items():
            z += weights.get(categories[name], 0.0)
        return min(max(1 / (1 + math.exp(-min(max(z, -30), 30))), 1e-7), 1 - 1e-7)
