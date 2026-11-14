"""Shared, causal booking features for training and online prediction.

Fit price reference statistics on the model's training rows only. Group counters
belong to an observation stream, not to the fitted transformer or an acceptance
ledger: pass the same counter through commitments and every incoming request.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

import numpy as np
import pandas as pd


MISSING_CATEGORY = "_MISSING_"
CATEGORICAL_FEATURES = (
    "hotel", "arrival_month", "arrival_weekday", "booking_month",
    "booking_weekday", "meal", "country", "sales_segment", "sales_channel",
    "room_type", "agent", "company", "guest_type",
)
NUMERIC_FEATURES = (
    "days_ahead", "arrival_week", "nights", "weekend_nights", "weekday_nights",
    "weekend_share", "adults", "children", "babies", "total_guests", "has_kids",
    "returning_guest", "past_cancellations", "past_stays", "amendments",
    "waitlist_days", "nightly_rate", "rate_vs_typical", "stay_value",
    "special_requests", "is_free", "block_size_so_far",
)
FEATURE_COLUMNS = CATEGORICAL_FEATURES + NUMERIC_FEATURES
# Season labels are still built, but the cancellation model does not see them.
# With one or two years of history they memorise that year's cancellation level
# instead of guest behaviour; out of time, dropping them cut log loss from 0.58
# to 0.49 and removed a 7-point bias (scripts/analysis/calibration_check.py).
EXCLUDED_FROM_MODEL = ("arrival_month", "booking_month", "arrival_week")
MODEL_FEATURES = tuple(c for c in FEATURE_COLUMNS if c not in EXCLUDED_FROM_MODEL)
MODEL_CATEGORICAL = tuple(c for c in CATEGORICAL_FEATURES if c not in EXCLUDED_FROM_MODEL)
_DERIVED_NUMERIC = {
    "arrival_week", "weekend_share", "total_guests", "has_kids",
    "rate_vs_typical", "stay_value", "is_free", "block_size_so_far",
}


def _missing(value: Any) -> bool:
    return value is None or bool(pd.isna(value))


def _category(value: Any) -> str:
    return MISSING_CATEGORY if _missing(value) else str(value)


def _identifier(value: Any) -> str:
    """Use the same ID for 304, 304.0 and the CSV/string forms of either."""
    if _missing(value):
        return MISSING_CATEGORY
    text = str(value).strip()
    try:
        number = Decimal(text)
        if number.is_finite():
            return format(number.normalize(), "f")
    except InvalidOperation:
        pass
    return text


def _number(value: Any) -> float:
    if _missing(value):
        return float("nan")
    number = float(value)
    # CatBoost accepts NaN but not arbitrary infinities as useful measurements.
    return number if np.isfinite(number) else float("nan")


def _date(value: Any) -> pd.Timestamp:
    if _missing(value):
        return pd.NaT
    result = pd.Timestamp(value)
    if result.tzinfo is not None:
        result = result.tz_localize(None)
    return result.normalize()


def _date_key(value: Any) -> str:
    date = _date(value)
    return MISSING_CATEGORY if pd.isna(date) else date.isoformat()


def _number_key(value: Any) -> float | None:
    number = _number(value)
    # NaN is not equal to itself and cannot safely represent a missing key.
    return None if np.isnan(number) else number


def block_key(row: Mapping[str, Any]) -> tuple:
    """The permitted group key, including booking date to avoid merging trips."""
    return (
        _category(row.get("hotel")), _date_key(row.get("booking_date")),
        _date_key(row.get("arrival_date")), _number_key(row.get("nights")),
        _identifier(row.get("agent")), _number_key(row.get("nightly_rate")),
        _category(row.get("room_type")), _category(row.get("sales_segment")),
    )


@dataclass
class GroupCounter:
    """Counts all observations, including the current request and rejections."""

    counts: dict[tuple, int] = field(default_factory=dict)

    def observe(self, row: Mapping[str, Any]) -> int:
        key = block_key(row)
        count = self.counts.get(key, 0) + 1
        self.counts[key] = count
        return count


class FeatureBuilder:
    """Training-fitted prices plus identical batch and dict feature paths."""

    def __init__(self) -> None:
        self.rate_medians: dict[tuple[str, int], float] = {}
        self.hotel_rate_medians: dict[str, float] = {}
        self.global_rate_median: float = float("nan")
        self.fitted = False

    def fit(self, rows: pd.DataFrame) -> FeatureBuilder:
        """Learn only price medians; callers supply the training partition."""
        if rows.empty:
            raise ValueError("Cannot fit price references on an empty training set")
        references = pd.DataFrame({
            "hotel": [_category(x) for x in rows["hotel"]],
            "month": [d.month if not pd.isna(d) else np.nan
                      for d in map(_date, rows["arrival_date"])],
            "rate": [_number(x) for x in rows["nightly_rate"]],
        })
        self.rate_medians = {
            (str(hotel), int(month)): float(value)
            for (hotel, month), value in references.groupby(
                ["hotel", "month"], sort=False
            )["rate"].median().items() if pd.notna(value)
        }
        self.hotel_rate_medians = {
            str(hotel): float(value)
            for hotel, value in references.groupby("hotel", sort=False)["rate"].median().items()
            if pd.notna(value)
        }
        rates = references["rate"].dropna()
        self.global_rate_median = float(rates.median()) if len(rates) else float("nan")
        self.fitted = True
        return self

    def make_feature_row(self, booking: Mapping[str, Any], state: GroupCounter) -> list:
        """Observe one request and return CatBoost's fixed-order feature vector.

        This path creates no DataFrame. It must be called once for every request,
        before the policy decides whether to accept it.
        """
        if not self.fitted:
            raise RuntimeError("Fit FeatureBuilder before transforming bookings")
        arrival = _date(booking.get("arrival_date"))
        booked = _date(booking.get("booking_date"))
        values = {name: _category(booking.get(name)) for name in CATEGORICAL_FEATURES}
        values["agent"] = _identifier(booking.get("agent"))
        values["company"] = _identifier(booking.get("company"))
        values["meal"] = "SC" if values["meal"] == "Undefined" else values["meal"]
        for name, date, attribute in (
            ("arrival_month", arrival, "month"),
            ("arrival_weekday", arrival, "day_of_week"),
            ("booking_month", booked, "month"),
            ("booking_weekday", booked, "day_of_week"),
        ):
            values[name] = MISSING_CATEGORY if pd.isna(date) else str(getattr(date, attribute))
        for name in NUMERIC_FEATURES:
            if name not in _DERIVED_NUMERIC:
                values[name] = _number(booking.get(name))
        rate, nights = values["nightly_rate"], values["nights"]
        month = arrival.month if pd.notna(arrival) else None
        typical = self.rate_medians.get(
            (values["hotel"], month),
            self.hotel_rate_medians.get(values["hotel"], self.global_rate_median),
        )
        values.update({
            "arrival_week": float(arrival.isocalendar().week) if pd.notna(arrival) else np.nan,
            "weekend_share": values["weekend_nights"] / nights if nights > 0 else np.nan,
            "total_guests": values["adults"] + values["children"] + values["babies"],
            "has_kids": float(values["children"] + values["babies"] > 0)
            if np.isfinite(values["children"] + values["babies"]) else np.nan,
            "rate_vs_typical": rate / typical if typical > 0 else np.nan,
            "stay_value": rate * nights,
            "is_free": float(rate == 0) if np.isfinite(rate) else np.nan,
            "block_size_so_far": float(state.observe(booking)),
        })
        return [values[name] for name in FEATURE_COLUMNS]

    def make_features(
        self, rows: pd.DataFrame | Mapping[str, Any], state: GroupCounter | None = None,
    ) -> pd.DataFrame:
        """Scan chronologically while preserving the caller's row order/index.

        A fresh counter is used unless explicitly supplied. To seed live state,
        transform commitments with a counter and reuse it for new requests.
        """
        if not self.fitted:
            raise RuntimeError("Fit FeatureBuilder before transforming bookings")
        frame = pd.DataFrame([rows]) if isinstance(rows, Mapping) else rows
        counter = GroupCounter() if state is None else state
        records = frame.to_dict("records")

        def order(position: int) -> tuple:
            row = records[position]
            date = _date(row.get("booking_date"))
            identifier = row.get("booking_id", position)
            try:
                number = _number(identifier)
                tie = (0, number) if np.isfinite(number) else (2, position)
            except (ValueError, TypeError):
                tie = (1, str(identifier))
            return (pd.Timestamp.max if pd.isna(date) else date, tie, position)

        features: list[list | None] = [None] * len(records)
        for position in sorted(range(len(records)), key=order):
            features[position] = self.make_feature_row(records[position], counter)
        result = pd.DataFrame(features, columns=list(FEATURE_COLUMNS), index=frame.index)
        # Keep batch and one-row table dtypes stable, including empty partitions.
        for name in CATEGORICAL_FEATURES:
            result[name] = result[name].astype(object)
        for name in NUMERIC_FEATURES:
            result[name] = result[name].astype(float)
        return result

    def to_dict(self) -> dict:
        """JSON-safe fitted statistics; live group state is deliberately separate."""
        if not self.fitted:
            raise RuntimeError("Cannot serialize an unfitted FeatureBuilder")
        return {
            "version": 1,
            "feature_columns": list(FEATURE_COLUMNS),
            "rate_medians": [
                {"hotel": hotel, "month": month, "median": median}
                for (hotel, month), median in sorted(self.rate_medians.items())
            ],
            "hotel_rate_medians": self.hotel_rate_medians.copy(),
            "global_rate_median": self.global_rate_median
            if np.isfinite(self.global_rate_median) else None,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> FeatureBuilder:
        if payload.get("version") != 1 or payload.get("feature_columns") != list(FEATURE_COLUMNS):
            raise ValueError("Unsupported preprocessing schema")
        result = cls()
        result.rate_medians = {
            (row["hotel"], int(row["month"])): float(row["median"])
            for row in payload["rate_medians"]
        }
        result.hotel_rate_medians = {
            hotel: float(rate) for hotel, rate in payload["hotel_rate_medians"].items()
        }
        result.global_rate_median = _number(payload["global_rate_median"])
        result.fitted = True
        return result
