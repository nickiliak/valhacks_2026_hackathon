"""Transparent replay baselines; all online policies are outcome-blind."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from hackathon.simulator import PreparedReplay, ReplayResult, score_accepted


class AcceptAll:
    def __init__(self, commitments: pd.DataFrame, capacity: dict[str, pd.Series]) -> None:
        pass

    def decide(self, booking: dict) -> bool:
        return True


class RejectAll(AcceptAll):
    def decide(self, booking: dict) -> bool:
        return False


class CapacityCap:
    """Simple capacity cap; commitments consume the same weight as requests."""

    def __init__(self, commitments: pd.DataFrame, capacity: dict[str, pd.Series],
                 show_rates: Mapping[str, float] | None = None) -> None:
        self.capacity = {h: s.to_numpy(dtype=float, copy=True) for h, s in capacity.items()}
        self.dates = {h: s.index for h, s in capacity.items()}
        self.used = {h: np.zeros(len(s), dtype=float) for h, s in capacity.items()}
        self.weights = {h: 1.0 if show_rates is None else float(show_rates[h]) for h in capacity}
        if any(not np.isfinite(w) or not 0 <= w <= 1 for w in self.weights.values()):
            raise ValueError("Show rates must be finite probabilities")
        for booking in commitments.to_dict(orient="records"):
            hotel, begin, stop = self._stay(booking)
            self.used[hotel][begin:stop] += self.weights[hotel]

    def _stay(self, booking: dict) -> tuple[str, int, int]:
        hotel = booking["hotel"]
        arrival = pd.Timestamp(booking["arrival_date"])
        departure = arrival + pd.Timedelta(days=int(booking["nights"]))
        return hotel, int(self.dates[hotel].searchsorted(arrival)), int(self.dates[hotel].searchsorted(departure))

    def decide(self, booking: dict) -> bool:
        hotel, begin, stop = self._stay(booking)
        weight = self.weights[hotel]
        if np.all(self.used[hotel][begin:stop] + weight <= self.capacity[hotel][begin:stop] + 1e-12):
            self.used[hotel][begin:stop] += weight
            return True
        return False


def historical_show_rates(bookings: pd.DataFrame, cutoff, hotels) -> dict[str, float]:
    """Use only labels whose arrival is strictly before the replay cutoff."""
    history = bookings.loc[pd.to_datetime(bookings.arrival_date) < pd.Timestamp(cutoff)]
    rates = 1 - history.groupby("hotel").cancelled.mean()
    # No history means assume everyone shows, avoiding unsupported overbooking.
    return {h: float(rates.get(h, 1.0)) for h in hotels}


def average_rate_factory(show_rates: Mapping[str, float]):
    rates = dict(show_rates)

    def factory(commitments, capacity):
        return CapacityCap(commitments, capacity, rates)

    return factory


def greedy_hindsight(prepared: PreparedReplay) -> ReplayResult:
    """Feasible offline greedy policy, a lower bound on the true optimum.

    Existing commitments stay mandatory, even when they already overflow.
    Reserving every showing commitment can be conservative when some are
    walked; this remains an attainable policy, never an upper bound.
    """
    free = {h: s.to_numpy(dtype=int, copy=True) for h, s in prepared.capacity.items()}
    frame = prepared.bookings

    def bounds(row):
        begin = (row.arrival_date - prepared.dates[0]).days
        return begin, min(begin + row.nights, len(prepared.dates))

    for row in frame.loc[frame.committed & frame.cancelled.eq(0)].itertuples(index=False):
        begin, stop = bounds(row)
        free[row.hotel][begin:stop] -= 1
    selected = []
    candidates = frame.loc[~frame.committed & frame.cancelled.eq(0)].copy()
    if prepared.rules.horizon == "truncate":
        nights = np.minimum(candidates.nights, (prepared.dates[-1] - candidates.arrival_date).dt.days + 1)
        candidates["stay_value"] = candidates.nightly_rate * nights
    for row in candidates.sort_values(["stay_value", "booking_id"], ascending=[False, True], kind="stable").itertuples(index=False):
        begin, stop = bounds(row)
        if (free[row.hotel][begin:stop] > 0).all():
            selected.append(row.booking_id)
            free[row.hotel][begin:stop] -= 1
    result = score_accepted(prepared, selected)
    result.summary["baseline"] = "greedy hindsight (feasible lower bound, not an upper bound)"
    return result
