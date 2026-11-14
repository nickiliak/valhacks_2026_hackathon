"""Deterministic historical reconstruction of the challenge scorer.

All state is local to a run. In particular, accepted sets never reuse another
run's occupancy. Before the replay, we seat historical arrivals under an
accept-all policy to reconstruct carry-over guests; the source data does not
record actual seating. Callers with known occupancy can supply it explicitly.
This is our reconstruction, not the organisers' locked scorer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

import numpy as np
import pandas as pd

from hackathon.contracts import ROOMS

_PRIVATE_COLUMNS = ("cancelled", "deposit")


@dataclass(frozen=True)
class ScoringRules:
    cheapest: str = "stay_value"
    horizon: str = "full"
    walked_guests_release_rooms: bool = True
    walk_penalty: float = 2.5

    def __post_init__(self) -> None:
        if self.cheapest not in {"stay_value", "nightly_rate"}:
            raise ValueError("cheapest must be stay_value or nightly_rate")
        if self.horizon not in {"full", "truncate"}:
            raise ValueError("horizon must be full or truncate")
        if not np.isfinite(self.walk_penalty) or self.walk_penalty < 0:
            raise ValueError("walk_penalty must be finite and nonnegative")


@dataclass
class PreparedReplay:
    bookings: pd.DataFrame
    commitments: pd.DataFrame
    requests: pd.DataFrame
    capacity: dict[str, pd.Series]
    rooms: dict[str, int]
    dates: pd.DatetimeIndex
    rules: ScoringRules
    initial_state_source: str


@dataclass
class ReplayResult:
    summary: dict
    by_hotel: pd.DataFrame
    by_month: pd.DataFrame
    daily_occupancy: pd.DataFrame
    decisions: pd.DataFrame
    capacity: dict[str, pd.Series]


def _normalise(bookings: pd.DataFrame, rooms: Mapping[str, int]) -> pd.DataFrame:
    required = {"booking_id", "hotel", "booking_date", "arrival_date", "nights", "nightly_rate", "cancelled"}
    missing = required.difference(bookings.columns)
    if missing:
        raise ValueError(f"Missing booking columns: {sorted(missing)}")
    frame = bookings.drop(columns=["deposit"], errors="ignore").copy().reset_index(drop=True)
    for column in ("booking_date", "arrival_date"):
        frame[column] = pd.to_datetime(frame[column], errors="raise").dt.normalize()
        if frame[column].isna().any():
            raise ValueError(f"Missing {column}")
    if frame.booking_id.isna().any() or frame.booking_id.duplicated().any():
        raise ValueError("booking_id must be present and unique")
    if not frame.hotel.isin(rooms).all():
        raise ValueError("Bookings contain an unknown hotel")
    if (frame.booking_date > frame.arrival_date).any():
        raise ValueError("A booking cannot be made after arrival")
    for column in ("nights", "nightly_rate", "cancelled"):
        frame[column] = pd.to_numeric(frame[column], errors="raise")
        if not np.isfinite(frame[column]).all():
            raise ValueError(f"Nonfinite {column}")
    if ((frame.nights <= 0) | (frame.nights % 1 != 0)).any():
        raise ValueError("nights must be positive integers")
    if (frame.nightly_rate < 0).any() or not frame.cancelled.isin([0, 1]).all():
        raise ValueError("Rates must be nonnegative and cancelled must be binary")
    frame["nights"] = frame.nights.astype(int)
    frame["stay_value"] = frame.nightly_rate * frame.nights
    return frame


def _seat(
    bookings: pd.DataFrame,
    dates: pd.DatetimeIndex,
    capacity: Mapping[str, pd.Series],
    rules: ScoringRules,
) -> tuple[pd.DataFrame, dict[str, np.ndarray], dict[str, np.ndarray]]:
    """Seat showing, accepted arrivals; carry seated guests until departure.

    Capacity already excludes pre-window guests. Walks reserve no future rooms
    by default. The alternative switch retains ghost reservations solely for
    sensitivity analysis of the ambiguous rule.
    """
    outcomes = pd.DataFrame(index=bookings.index)
    outcomes["status"] = "cancelled"
    outcomes["revenue"] = 0.0
    outcomes["penalties"] = 0.0
    occupied = {hotel: np.zeros(len(dates), dtype=np.int64) for hotel in capacity}
    blocked = {hotel: np.zeros(len(dates), dtype=np.int64) for hotel in capacity}
    showing = bookings.loc[bookings.cancelled.eq(0)].sort_values(
        ["arrival_date", rules.cheapest, "booking_id"],
        ascending=[True, False, True], kind="stable",
    )
    cap = {hotel: series.to_numpy(dtype=np.int64) for hotel, series in capacity.items()}
    day0 = dates[0]
    for index, row in zip(showing.index, showing.itertuples(index=False)):
        day = (row.arrival_date - day0).days
        if not 0 <= day < len(dates):
            raise ValueError("Scored arrival falls outside the capacity horizon")
        stop = min(day + row.nights, len(dates))
        value = row.nightly_rate * (row.nights if rules.horizon == "full" else stop - day)
        hotel = row.hotel
        if blocked[hotel][day] < cap[hotel][day]:
            outcomes.at[index, "status"] = "seated"
            outcomes.at[index, "revenue"] = value
            occupied[hotel][day:stop] += 1
            blocked[hotel][day:stop] += 1
        else:
            outcomes.at[index, "status"] = "walked"
            outcomes.at[index, "penalties"] = rules.walk_penalty * value
            if not rules.walked_guests_release_rooms:
                blocked[hotel][day:stop] += 1
    return outcomes, occupied, blocked


def prepare_replay(
    bookings: pd.DataFrame,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    *,
    rooms: Mapping[str, int] | None = None,
    rules: ScoringRules | None = None,
    initial_in_house: Mapping[str, pd.Series] | None = None,
) -> PreparedReplay:
    """Prepare an inclusive arrival horizon and outcome-free policy inputs.

    ``initial_in_house`` describes ONLY guests arriving before ``start``, one
    count for every horizon night. These counts cannot increase over time.
    If omitted, a full-history seating warm-up resolves pre-window walks.
    """
    room_counts = dict(ROOMS if rooms is None else rooms)
    if not room_counts or any(int(n) != n or n <= 0 for n in room_counts.values()):
        raise ValueError("Room counts must be positive integers")
    room_counts = {h: int(n) for h, n in room_counts.items()}
    scoring = rules or ScoringRules()
    first, last = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    if pd.isna(first) or pd.isna(last) or last < first:
        raise ValueError("Replay start must precede or equal end")
    dates = pd.date_range(first, last, name="date")
    frame = _normalise(bookings, room_counts)
    carry = {h: np.zeros(len(dates), dtype=np.int64) for h in room_counts}
    if initial_in_house is not None:
        if set(initial_in_house) != set(room_counts):
            raise ValueError("initial_in_house must contain exactly the configured hotels")
        for hotel, counts in initial_in_house.items():
            if not counts.index.equals(dates):
                raise ValueError("initial_in_house must have exactly the replay date index")
            values = counts.to_numpy(dtype=float)
            if (not np.isfinite(values).all() or (values % 1 != 0).any()
                    or (values < 0).any() or (values > room_counts[hotel]).any()
                    or (np.diff(values) > 0).any()):
                raise ValueError("Pre-window occupancy must be integral, within rooms, and nonincreasing")
            carry[hotel] = values.astype(np.int64)
        state_source = "explicit initial_in_house"
    else:
        previous = frame.loc[frame.arrival_date.lt(first)]
        if not previous.empty:
            # Start at the earliest historical arrival, not merely at the oldest
            # carry-over: earlier walks can determine which long stays survive.
            warm_dates = pd.date_range(previous.arrival_date.min(), last)
            warm_capacity = {h: pd.Series(n, index=warm_dates) for h, n in room_counts.items()}
            _, _, warm_blocked = _seat(previous, warm_dates, warm_capacity, scoring)
            for hotel in room_counts:
                carry[hotel] = warm_blocked[hotel][-len(dates):].copy()
        state_source = "accept-all historical seating warm-up"
    capacity = {
        h: pd.Series(np.maximum(n - carry[h], 0), index=dates, name="free_rooms")
        for h, n in room_counts.items()
    }
    window = frame.loc[frame.arrival_date.between(first, last)].copy()
    window["committed"] = window.booking_date.lt(first)
    window = window.sort_values(["booking_date", "booking_id"], kind="stable").reset_index(drop=True)
    # Derived scorer columns must not change the official request schema.
    inputs = window.drop(columns=[*_PRIVATE_COLUMNS, "stay_value", "committed"], errors="ignore")
    return PreparedReplay(
        bookings=window,
        commitments=inputs.loc[window.committed].copy(),
        requests=inputs.loc[~window.committed].copy(),
        capacity=capacity,
        rooms=room_counts,
        dates=dates,
        rules=scoring,
        initial_state_source=state_source,
    )


def _metrics(log: pd.DataFrame, daily: pd.DataFrame) -> dict:
    requests = log.loc[~log.committed]
    accepted = int(requests.accepted.sum())
    available_room_nights = int(daily.rooms.sum())
    occupied_room_nights = int(daily.occupied.sum())
    revenue, penalties = float(log.revenue.sum()), float(log.penalties.sum())
    return {
        "revenue": revenue, "penalties": penalties, "net_revenue": revenue - penalties,
        "walks": int(log.status.eq("walked").sum()),
        "seated": int(log.status.eq("seated").sum()),
        "commitments": int(log.committed.sum()),
        "requests": len(requests), "accepted_requests": accepted,
        "accept_rate": accepted / len(requests) if len(requests) else 0.0,
        "occupied_room_nights": occupied_room_nights,
        "available_room_nights": available_room_nights,
        "average_occupancy": occupied_room_nights / available_room_nights if available_room_nights else 0.0,
    }


def score_accepted(prepared: PreparedReplay, accepted_ids) -> ReplayResult:
    """Score selected request IDs plus every commitment using fresh state.

    This is also the low-level hook for cached *decisions* or oracle baselines.
    Its occupancy is never cached: changing one early guest can affect every
    later night, even after that guest's own departure.
    """
    log = prepared.bookings.copy(deep=True)
    selected = set(accepted_ids)
    unknown = selected.difference(log.booking_id)
    if unknown:
        raise ValueError(f"Unknown accepted booking IDs: {list(unknown)[:5]}")
    log["accepted"] = log.committed | log.booking_id.isin(selected)
    log["status"] = "rejected"
    log["revenue"] = 0.0
    log["penalties"] = 0.0
    outcomes, occupied, blocked = _seat(log.loc[log.accepted], prepared.dates, prepared.capacity, prepared.rules)
    log.loc[outcomes.index, ["status", "revenue", "penalties"]] = outcomes
    log["net_revenue"] = log.revenue - log.penalties
    daily_parts = []
    for hotel, rooms in prepared.rooms.items():
        capacity = prepared.capacity[hotel].to_numpy(dtype=int)
        carry = rooms - capacity
        daily_parts.append(pd.DataFrame({
            "hotel": hotel, "date": prepared.dates, "rooms": rooms,
            "capacity": capacity, "carried_in": carry,
            "occupied": carry + occupied[hotel],
            "blocked": carry + blocked[hotel],
            "occupancy_rate": (carry + occupied[hotel]) / rooms,
        }))
    daily = pd.concat(daily_parts, ignore_index=True)
    by_hotel = pd.DataFrame([
        {"hotel": h, **_metrics(log.loc[log.hotel.eq(h)], daily.loc[daily.hotel.eq(h)])}
        for h in prepared.rooms
    ])
    monthly = []
    for hotel in prepared.rooms:
        for month in prepared.dates.to_period("M").unique():
            subset = log.loc[log.hotel.eq(hotel) & log.arrival_date.dt.to_period("M").eq(month)]
            nights = daily.loc[daily.hotel.eq(hotel) & daily.date.dt.to_period("M").eq(month)]
            monthly.append({"hotel": hotel, "month": str(month), **_metrics(subset, nights)})
    summary = _metrics(log, daily)
    summary.update({
        "start": str(prepared.dates[0].date()), "end": str(prepared.dates[-1].date()),
        "cheapest": prepared.rules.cheapest, "horizon": prepared.rules.horizon,
        "walked_guests_release_rooms": prepared.rules.walked_guests_release_rooms,
        "walk_penalty": prepared.rules.walk_penalty,
        "initial_state_source": prepared.initial_state_source,
        "scorer": "our reconstruction of the scorer",
    })
    return ReplayResult(summary, by_hotel, pd.DataFrame(monthly), daily, log,
                        {h: v.copy() for h, v in prepared.capacity.items()})


def replay(
    bookings: pd.DataFrame,
    solution_factory: Callable,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    *,
    rooms: Mapping[str, int] | None = None,
    rules: ScoringRules | None = None,
    initial_in_house: Mapping[str, pd.Series] | None = None,
) -> ReplayResult:
    prepared = prepare_replay(bookings, start, end, rooms=rooms, rules=rules, initial_in_house=initial_in_house)
    return replay_prepared(prepared, solution_factory)


def replay_prepared(prepared: PreparedReplay, solution_factory: Callable) -> ReplayResult:
    """Run exactly one policy instance for both hotels, globally ordered."""
    solution = solution_factory(
        prepared.commitments.copy(deep=True),
        {h: values.copy(deep=True) for h, values in prepared.capacity.items()},
    )
    accepted = []
    for booking in prepared.requests.to_dict(orient="records"):
        decision = solution.decide(booking)
        if not isinstance(decision, (bool, np.bool_)):
            raise TypeError("Solution.decide must return a bool")
        if decision:
            accepted.append(booking["booking_id"])
    return score_accepted(prepared, accepted)


def slice_result(result: ReplayResult, start, end=None) -> ReplayResult:
    """Report a period of an existing replay without restarting policy state.

    For S2 confirmation, replay frozen settings from July through December and
    select October onward here. Starting a new replay in October would turn
    previously rejected requests into mandatory commitments and change state.
    Revenue and penalties are attributed to arrival month; occupancy is nightly.
    """
    first = pd.Timestamp(start).normalize()
    last = pd.Timestamp(result.summary["end"] if end is None else end).normalize()
    if first < pd.Timestamp(result.summary["start"]) or last > pd.Timestamp(result.summary["end"]) or first > last:
        raise ValueError("Reporting period must be within the original replay")
    log = result.decisions.loc[result.decisions.arrival_date.between(first, last)].copy()
    daily = result.daily_occupancy.loc[result.daily_occupancy.date.between(first, last)].copy()
    hotels = list(result.capacity)
    by_hotel = pd.DataFrame([
        {"hotel": h, **_metrics(log.loc[log.hotel.eq(h)], daily.loc[daily.hotel.eq(h)])}
        for h in hotels
    ])
    monthly = []
    for hotel in hotels:
        for month in pd.date_range(first, last).to_period("M").unique():
            subset = log.loc[log.hotel.eq(hotel) & log.arrival_date.dt.to_period("M").eq(month)]
            nights = daily.loc[daily.hotel.eq(hotel) & daily.date.dt.to_period("M").eq(month)]
            monthly.append({"hotel": hotel, "month": str(month), **_metrics(subset, nights)})
    summary = {
        **result.summary, **_metrics(log, daily),
        "replay_start": result.summary.get("replay_start", result.summary["start"]),
        "replay_end": result.summary.get("replay_end", result.summary["end"]),
        "start": str(first.date()), "end": str(last.date()),
    }
    return ReplayResult(summary, by_hotel, pd.DataFrame(monthly), daily, log,
                        {h: values.loc[first:last].copy() for h, values in result.capacity.items()})
