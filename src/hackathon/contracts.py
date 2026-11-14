"""Shared booking interfaces. Policy inputs never include historical outcomes."""

from pathlib import Path
from typing import Any, Protocol

import numpy as np
import pandas as pd

ROOMS = {"Downtown Hotel": 124, "Seaside Hotel": 103}
HISTORY_END = pd.Timestamp("2017-01-01")  # Exclusive; never read evaluation data.
FORBIDDEN_INPUT_COLUMNS = frozenset({"cancelled", "deposit"})


class BookingPolicy(Protocol):
    def decide(self, booking: dict[str, Any]) -> bool: ...


class PolicyFactory(Protocol):
    def __call__(self, commitments: pd.DataFrame,
                 capacity: dict[str, pd.Series]) -> BookingPolicy: ...


class CancellationPredictor(Protocol):
    def p_cancel(self, rows: pd.DataFrame, *, state: Any = None) -> np.ndarray: ...


def policy_inputs(rows: pd.DataFrame) -> pd.DataFrame:
    return rows.drop(columns=list(FORBIDDEN_INPUT_COLUMNS), errors="ignore").copy()


def load_history(path: str | Path = "data/train.csv") -> pd.DataFrame:
    """Read the permitted training CSV; exclude deposit before parsing values."""
    rows = pd.read_csv(path, usecols=lambda name: name != "deposit",
                       parse_dates=["booking_date", "arrival_date"])
    required = {"booking_id", "hotel", "booking_date", "arrival_date", "nights",
                "nightly_rate", "cancelled"}
    missing = required.difference(rows.columns)
    if missing:
        raise ValueError(f"Historical data is missing columns: {sorted(missing)}")
    if rows.empty or rows[["booking_date", "arrival_date"]].isna().any().any():
        raise ValueError("History must contain bookings with valid dates")
    if (rows.arrival_date >= HISTORY_END).any():
        raise ValueError("Only the permitted pre-2017 training history may be used")
    if rows.booking_id.isna().any() or rows.booking_id.duplicated().any():
        raise ValueError("booking_id must be present and unique")
    if not rows.cancelled.isin([0, 1]).all():
        raise ValueError("cancelled must be binary")
    if not rows.hotel.isin(ROOMS).all():
        raise ValueError("Unknown hotel in historical data")
    if (rows.booking_date > rows.arrival_date).any():
        raise ValueError("Booking date must not follow arrival")
    if (rows.nights.isna().any() or (rows.nights <= 0).any()
            or (rows.nights % 1 != 0).any()):
        raise ValueError("nights must be positive integers")
    if not np.isfinite(rows.nightly_rate).all():
        raise ValueError("nightly_rate must be finite")
    return rows
