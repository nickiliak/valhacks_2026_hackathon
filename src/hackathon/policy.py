"""Accept/reject policy: probability ledger, nightly prices, simulated revenue differences.

Everything is per hotel; the two hotels share nothing.

1. Ledger. Each accepted booking uses p_show of a room on every night it covers.
2. Nightly minimum price. For each night we look at the guests who actually
   stayed on the same nights one year earlier and who booked closer to the
   night than today. Sorted by rate, they tell us what the rooms still free
   are worth: the price is the rate of the last guest who would still fit.
   This is a statistical table of past demand, not a second prediction model.
3. Revenue difference. A Monte Carlo replay of the scoring rules over the
   bookings already held, with and without the candidate on the same random
   draws (one coin per group block). It contains the candidate's own expected
   revenue, its chance of being walked, and the walks it causes.

A request is accepted when its rate beats the minimum price of its nights and
the simulated revenue difference is positive.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

from hackathon.preprocessing import GroupCounter, block_key

DEMAND_COLUMNS = ["hotel", "booking_date", "arrival_date", "nights", "nightly_rate", "cancelled"]
YEAR = 364  # 52 weeks: the same weekday one year earlier
FALLBACK_SHOW_WEIGHT = 0.75  # deliberately cautious room share for the crash fallback


@dataclass
class PolicyParams:
    load_target: float = 1.0        # share of free rooms the expected-rooms ledger may fill
    price_mult: float = 1.0         # multiplier on the nightly minimum prices
    rate_scale: float | None = None  # None: measured from the commitments (thermometer)
    demand_scale: float | None = 1.0  # None: measured from the commitments
    margin: float = 0.0             # required revenue difference, as a share of p_show x stay value
    raw_cap: float = 2.5            # guardrail: bookings per night <= raw_cap x free rooms
    use_prices: bool = True
    price_when_full: bool = False   # True: on a full night demand the top expected future rate
    risk: str = "mc"                # "mc" or "none"
    draws: int = 200
    tail: int = 21                  # nights simulated beyond the candidate's stay
    logit_noise: float = 0.0        # shared uncertainty about the probabilities themselves
    analog_weeks: tuple = (-1, 0, 1)
    cheapest: str = "stay_value"
    p_floor: float = 0.03
    walk_penalty: float = 2.5
    seed: int = 2026

    @classmethod
    def from_dict(cls, payload: Mapping) -> PolicyParams:
        known = {f.name for f in fields(cls)}
        values = {k: v for k, v in payload.items() if k in known}
        if "analog_weeks" in values:
            values["analog_weeks"] = tuple(values["analog_weeks"])
        return cls(**values)


class DemandHistory:
    """Past show-up demand per hotel night: rate paid and days booked ahead."""

    def __init__(self, frame: pd.DataFrame, cutoff) -> None:
        self.cutoff = pd.Timestamp(cutoff).normalize()
        frame = frame[DEMAND_COLUMNS].copy()
        for column in ("booking_date", "arrival_date"):
            frame[column] = pd.to_datetime(frame[column]).dt.normalize()
        if (frame.arrival_date >= self.cutoff).any():
            raise ValueError("Demand history contains arrivals on or after its cutoff")
        self.frame = frame.reset_index(drop=True)
        self.first_night = self.frame.arrival_date.min() + pd.Timedelta(days=7)
        self._nightly: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        for hotel, part in self.frame.loc[self.frame.cancelled.eq(0)].groupby("hotel"):
            nights = part.nights.to_numpy(dtype=int)
            offsets = np.concatenate([np.arange(n) for n in nights]) if len(nights) else np.empty(0, int)
            night = np.repeat(part.arrival_date.to_numpy("datetime64[D]"), nights) + offsets
            booked = np.repeat(part.booking_date.to_numpy("datetime64[D]"), nights)
            rate = np.repeat(part.nightly_rate.to_numpy(dtype=float), nights)
            order = np.argsort(night, kind="stable")
            self._nightly[str(hotel)] = (night[order], (night - booked).astype(int)[order], rate[order])

    @classmethod
    def from_rows(cls, rows: pd.DataFrame, cutoff) -> DemandHistory:
        arrival = pd.to_datetime(rows.arrival_date)
        return cls(rows.loc[arrival < pd.Timestamp(cutoff)], cutoff)

    def night_table(self, hotel: str, night: pd.Timestamp, weeks=(-1, 0, 1)) -> tuple[np.ndarray, np.ndarray, int]:
        """Guests who stayed on comparable nights a year earlier.

        Returns (days booked before the night, nightly rate) sorted by rate,
        highest first, and the number of comparable nights pooled.
        """
        if hotel not in self._nightly:
            return np.empty(0, int), np.empty(0), 0
        nights, leads, rates = self._nightly[hotel]
        lead_parts, rate_parts, used = [], [], 0
        for week in weeks:
            analog = night - pd.Timedelta(days=YEAR) + pd.Timedelta(days=7 * week)
            if not self.first_night <= analog < self.cutoff:
                continue
            day = np.datetime64(analog, "D")
            low, high = np.searchsorted(nights, day, "left"), np.searchsorted(nights, day, "right")
            lead_parts.append(leads[low:high])
            rate_parts.append(rates[low:high])
            used += 1
        if not used:
            return np.empty(0, int), np.empty(0), 0
        lead, rate = np.concatenate(lead_parts), np.concatenate(rate_parts)
        order = np.argsort(-rate, kind="stable")
        return lead[order], rate[order], used

    def save(self, path: str | Path) -> None:
        frame = self.frame.copy()
        frame.attrs = {}
        frame.to_parquet(path, index=False)
        Path(path).with_suffix(".json").write_text(json.dumps({"cutoff": str(self.cutoff.date())}), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> DemandHistory:
        cutoff = json.loads(Path(path).with_suffix(".json").read_text(encoding="utf-8"))["cutoff"]
        return cls(pd.read_parquet(path), cutoff)


def thermometer(commitments: pd.DataFrame, history: pd.DataFrame, start, end) -> dict[str, dict]:
    """Compare the bookings already on hand with those on hand a year earlier.

    Like with like: commitments are long-lead bookings, so they are compared
    with bookings that had also been made before the same day last year, month
    by month. Returns a price ratio and a volume ratio per hotel.
    """
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    shift = pd.Timedelta(days=YEAR)
    result = {}
    arrival = pd.to_datetime(history.arrival_date) + shift
    reference_all = history.loc[(arrival >= start) & (arrival <= end)
                                & (pd.to_datetime(history.booking_date) + shift < start)]
    for hotel in sorted(set(commitments.hotel) | set(history.hotel)):
        current = commitments.loc[commitments.hotel.eq(hotel) & (commitments.nightly_rate > 0)]
        reference = reference_all.loc[reference_all.hotel.eq(hotel) & (reference_all.nightly_rate > 0)]
        entry = {"rate": 1.0, "volume": 1.0, "current": len(current), "reference": len(reference)}
        if len(current) >= 50 and len(reference) >= 50:
            now = current.groupby(pd.to_datetime(current.arrival_date).dt.month).nightly_rate.agg(["median", "size"])
            then = reference.groupby((pd.to_datetime(reference.arrival_date) + shift).dt.month).nightly_rate.agg(["median", "size"])
            both = now.add_suffix("_now").join(then.add_suffix("_then"), how="inner")
            both = both.loc[(both.size_now >= 30) & (both.size_then >= 30)]
            if len(both):
                weights = np.minimum(both.size_now, both.size_then)
                entry["rate"] = float(np.average(both.median_now / both.median_then, weights=weights))
                # Only months present in both years, so partial history cannot distort it.
                entry["volume"] = float(both.size_now.sum() / both.size_then.sum())
            else:
                entry["rate"] = float(current.nightly_rate.median() / reference.nightly_rate.median())
                entry["volume"] = len(current) / len(reference)
        entry["rate"] = float(np.clip(entry["rate"], 0.8, 1.8))
        entry["volume"] = float(np.clip(entry["volume"], 0.6, 1.6))
        result[str(hotel)] = entry
    return result


class RiskSim:
    """Replays the scoring rules for one hotel over many random show-up draws.

    Each draw is one possible future: every held booking either shows or not.
    Guests are seated in arrival order; a full night walks its cheapest
    arrivals; a seated guest keeps the room; a walked guest frees every night.
    """

    def __init__(self, capacity: np.ndarray, draws: int, penalty: float = 2.5, tail: int = 21) -> None:
        self.cap = np.asarray(capacity, dtype=np.float32)
        self.T, self.S = len(self.cap), int(draws)
        self.pen, self.tail = float(penalty), int(tail)
        self.occ = np.zeros((self.S, self.T), dtype=np.float32)  # seated guests in house, per draw and night
        self.key = [np.empty(0) for _ in range(self.T)]          # walk order: highest keeps the room
        self.val = [np.empty(0, dtype=np.float32) for _ in range(self.T)]
        self.len = [np.empty(0, dtype=np.int64) for _ in range(self.T)]
        self.show = [np.zeros((0, self.S), dtype=bool) for _ in range(self.T)]
        self.seat = [np.zeros((0, self.S), dtype=bool) for _ in range(self.T)]

    def _insert(self, t: int, key: float, value: float, nights: int, show: np.ndarray):
        position = int(np.searchsorted(-self.key[t], -key, side="right"))
        return (np.insert(self.key[t], position, key), np.insert(self.val[t], position, value),
                np.insert(self.len[t], position, nights), np.insert(self.show[t], position, show, axis=0),
                np.insert(self.seat[t], position, False, axis=0))

    def add(self, t: int, key: float, value: float, nights: int, show: np.ndarray) -> None:
        """Register a booking without reseating; call rebuild() afterwards."""
        self.key[t], self.val[t], self.len[t], self.show[t], self.seat[t] = self._insert(t, key, value, nights, show)

    def rebuild(self) -> None:
        self.occ[:] = 0
        self.seat = [np.zeros_like(s) for s in self.show]
        self._settle(0, self.T - 1)

    def _settle(self, start: int, dirty: int) -> None:
        """Reseat nights from ``start`` until changes stop propagating."""
        t = start
        while t <= dirty and t < self.T:
            show = self.show[t]
            if len(show):
                base = self.seat[t]
                free = self.cap[t] - (self.occ[:, t] - base.sum(axis=0))
                seated = show & (np.cumsum(show, axis=0) <= free)
                diff = seated.astype(np.float32) - base
                changed = diff.any(axis=1)
                if changed.any():
                    lens = self.len[t][changed]
                    width = min(self.T - t, int(lens.max()))
                    stay = (np.arange(width)[None, :] < lens[:, None]).astype(np.float32)
                    self.occ[:, t:t + width] += diff[changed].T @ stay
                    self.seat[t] = seated
                    dirty = max(dirty, t + width - 1)
            t += 1

    def evaluate(self, t0: int, nights: int, key: float, value: float, show: np.ndarray):
        """Expected net revenue with the booking minus without it, on the same draws."""
        limit = min(self.T, t0 + nights + self.tail)
        cur = self.occ[:, t0:min(self.T, limit + 45)].copy()
        columns = cur.shape[1]
        inserted = self._insert(t0, key, value, nights, show)
        gain = -self.pen * value * show.astype(np.float32)
        seats = {}
        dirty = min(t0 + nights - 1, self.T - 1)
        t = t0
        while t <= dirty and t < limit:
            col = t - t0
            if t == t0:
                _, vals, lens, shows, base = inserted
            else:
                if np.array_equal(cur[:, col], self.occ[:, t]):
                    t += 1
                    continue
                vals, lens, shows, base = self.val[t], self.len[t], self.show[t], self.seat[t]
            if len(vals):
                free = self.cap[t] - (cur[:, col] - base.sum(axis=0))
                seated = shows & (np.cumsum(shows, axis=0) <= free)
                diff = seated.astype(np.float32) - base
                changed = diff.any(axis=1)
                if changed.any():
                    longest = int(lens[changed].max())
                    width = min(columns - col, longest)
                    stay = (np.arange(width)[None, :] < lens[changed][:, None]).astype(np.float32)
                    cur[:, col:col + width] += diff[changed].T @ stay
                    # Seated earns v; walked costs penalty x v. Same shows in both worlds.
                    gain += ((1 + self.pen) * vals[changed]) @ diff[changed]
                    seats[t] = seated
                    dirty = max(dirty, t + longest - 1)
            t += 1
        truncated = t <= dirty and t < self.T
        return float(gain.mean()), (t0, inserted, seats, cur, t, dirty if truncated else -1)

    def commit(self, pending) -> None:
        t0, inserted, seats, cur, t_next, dirty = pending
        self.key[t0], self.val[t0], self.len[t0], self.show[t0], self.seat[t0] = inserted
        for t, seated in seats.items():
            self.seat[t] = seated
        self.occ[:, t0:t0 + cur.shape[1]] = cur
        if dirty >= 0:
            self._settle(t_next, dirty)

    def net(self) -> np.ndarray:
        """Net revenue of the held bookings in every draw."""
        total = np.zeros(self.S, dtype=np.float64)
        for vals, show, seat in zip(self.val, self.show, self.seat):
            if len(vals):
                total += vals.astype(np.float64) @ ((1 + self.pen) * seat - self.pen * show)
        return total

    def overflow_chance(self, t: int) -> float:
        """Share of draws in which night t has no free room left."""
        return float((self.occ[:, t] >= self.cap[t]).mean())


class _Hotel:
    def __init__(self, name: str, capacity: pd.Series, params: PolicyParams, seed: int) -> None:
        self.name = name
        self.dates = pd.DatetimeIndex(capacity.index).normalize()
        self.day0 = self.dates[0]
        self.T = len(self.dates)
        self.cap = capacity.to_numpy(dtype=float)
        self.used = np.zeros(self.T)             # expected rooms used per night
        self.raw = np.zeros(self.T, dtype=int)   # bookings held per night
        self.tables: list[tuple[np.ndarray, np.ndarray, int]] = [(np.empty(0, int), np.empty(0), 0)] * self.T
        self.rate_scale = 1.0
        self.demand_scale = 1.0
        self.rng = np.random.default_rng(seed)
        self.sim = RiskSim(self.cap, params.draws, params.walk_penalty, params.tail) if params.risk == "mc" else None
        self.uniforms: dict[tuple, np.ndarray] = {}
        self.noise = self.rng.normal(0.0, params.logit_noise, params.draws) if params.logit_noise > 0 else None

    def span(self, booking: Mapping) -> tuple[int, int, int]:
        arrival = pd.Timestamp(booking["arrival_date"]).normalize()
        nights = int(booking["nights"])
        t0 = (arrival - self.day0).days
        return t0, min(t0 + nights, self.T), nights


class AcceptancePolicy:
    """The official Solution interface, with injectable model, prices and settings."""

    def __init__(self, commitments: pd.DataFrame, capacity: dict[str, pd.Series], *,
                 demand: DemandHistory | None, model=None, p_show: Mapping | None = None,
                 params: PolicyParams | None = None, record: bool = False) -> None:
        if model is None and p_show is None:
            raise ValueError("Supply a cancellation model or cached show-up probabilities")
        self.params = params or PolicyParams()
        self.model, self.cache, self.demand = model, p_show, demand
        self.counter = GroupCounter()
        self.record = record
        self.log: list[dict] = []
        self.errors = 0
        self.hotels = {str(name): _Hotel(str(name), series, self.params, self.params.seed + i)
                       for i, (name, series) in enumerate(sorted(capacity.items()))}
        self._seed_commitments(commitments)
        self._build_prices(commitments)

    # ---- set-up ---------------------------------------------------------
    def _seed_commitments(self, commitments: pd.DataFrame) -> None:
        if len(commitments):
            if self.cache is not None:
                shows = np.array([self.cache[i] for i in commitments.booking_id])
            else:
                shows = 1.0 - self.model.p_cancel(commitments, state=self.counter)
            for booking, p in zip(commitments.to_dict(orient="records"), shows):
                hotel = self.hotels.get(str(booking["hotel"]))
                if hotel is None:
                    continue
                t0, stop, nights = hotel.span(booking)
                if not 0 <= t0 < hotel.T:
                    continue
                p = float(np.clip(p, self.params.p_floor, 1.0))
                hotel.used[t0:stop] += p
                hotel.raw[t0:stop] += 1
                if hotel.sim is not None:
                    rate = float(booking["nightly_rate"])
                    value = rate * nights
                    key = value if self.params.cheapest == "stay_value" else rate
                    hotel.sim.add(t0, key, value, stop - t0, self._draw(hotel, booking, p))
        for hotel in self.hotels.values():
            if hotel.sim is not None:
                hotel.sim.rebuild()

    def _build_prices(self, commitments: pd.DataFrame) -> None:
        self.thermometer = {}
        if self.demand is None or not self.params.use_prices:
            return
        first = min(h.dates[0] for h in self.hotels.values())
        last = max(h.dates[-1] for h in self.hotels.values())
        self.thermometer = thermometer(commitments, self.demand.frame, first, last)
        for hotel in self.hotels.values():
            measured = self.thermometer.get(hotel.name, {"rate": 1.0, "volume": 1.0})
            hotel.rate_scale = measured["rate"] if self.params.rate_scale is None else self.params.rate_scale
            hotel.demand_scale = measured["volume"] if self.params.demand_scale is None else self.params.demand_scale
            scale = hotel.rate_scale * self.params.price_mult
            tables = []
            for night in hotel.dates:
                lead, rate, pooled = self.demand.night_table(hotel.name, night, self.params.analog_weeks)
                tables.append((lead, rate * scale, pooled))
            hotel.tables = tables

    def _draw(self, hotel: _Hotel, booking: Mapping, p: float) -> np.ndarray:
        """Show/no-show in every draw; rows of one group block share the coin."""
        key = block_key(booking)
        uniform = hotel.uniforms.get(key)
        if uniform is None:
            uniform = hotel.rng.random(self.params.draws, dtype=np.float32)
            hotel.uniforms[key] = uniform
        if hotel.noise is not None:
            q = min(max(p, 1e-6), 1 - 1e-6)
            p = 1.0 / (1.0 + np.exp(-(np.log(q / (1 - q)) + hotel.noise)))
        return uniform < p

    # ---- pricing --------------------------------------------------------
    def min_price(self, hotel: _Hotel, t: int, lead: int) -> float:
        """Rate of the last expected future guest who still fits in the rooms left."""
        leads, rates, pooled = hotel.tables[t]
        if not pooled:
            return 0.0
        future = rates[leads < lead]
        if not len(future):
            return 0.0
        rooms_left = self.params.load_target * hotel.cap[t] - hotel.used[t]
        if rooms_left <= 0:
            # Already full in expectation: a new guest can only come in by walking
            # someone, and the revenue-difference simulation prices exactly that.
            return float(future[0]) + 0.01 if self.params.price_when_full else 0.0
        index = int(rooms_left * pooled / hotel.demand_scale)
        return float(future[index]) if index < len(future) else 0.0

    # ---- decisions ------------------------------------------------------
    def decide(self, booking: dict) -> bool:
        try:
            return self._decide(booking)
        except Exception as error:  # never crash the official run
            self.errors += 1
            if self.errors == 1:
                print(f"decide() fell back to the simple rule: {error!r}", file=sys.stderr)
            return self._fallback(booking)

    def _note(self, booking: Mapping, accepted: bool, reason: str, **details) -> bool:
        if self.record:
            self.log.append({"booking_id": booking.get("booking_id"), "accepted": accepted, "reason": reason, **details})
        return accepted

    def _decide(self, booking: dict) -> bool:
        # Score first: every observed request must update the group counter.
        if self.cache is not None:
            p = float(self.cache[booking["booking_id"]])
        else:
            p = 1.0 - self.model.p_cancel_one(booking, state=self.counter)
        p = float(np.clip(p, self.params.p_floor, 1.0))
        hotel = self.hotels[str(booking["hotel"])]
        t0, stop, nights = hotel.span(booking)
        rate = float(booking["nightly_rate"])
        if not 0 <= t0 < hotel.T or nights <= 0:
            return self._note(booking, False, "outside the planning horizon", p_show=p)
        if not rate > 0:
            return self._note(booking, False, "free booking: no revenue, only risk", p_show=p)
        if (hotel.raw[t0:stop] + 1 > self.params.raw_cap * hotel.cap[t0:stop]).any():
            return self._note(booking, False, "booking-count guardrail reached", p_show=p)
        covered = stop - t0
        minimum = 0.0
        if self.params.use_prices:
            lead = (pd.Timestamp(booking["arrival_date"]).normalize() - pd.Timestamp(booking["booking_date"]).normalize()).days
            minimum = sum(self.min_price(hotel, t, lead + t - t0) for t in range(t0, stop)) / covered
            if rate < minimum:
                return self._note(booking, False, f"rate {rate:.0f} below minimum price {minimum:.0f}",
                                  p_show=p, min_price=minimum)
        value = rate * nights
        delta, pending = None, None
        if hotel.sim is not None:
            key = value if self.params.cheapest == "stay_value" else rate
            delta, pending = hotel.sim.evaluate(t0, covered, key, value, self._draw(hotel, booking, p))
            if delta <= self.params.margin * p * value:
                return self._note(booking, False, "expected walk cost outweighs the revenue",
                                  p_show=p, min_price=minimum, delta=delta)
            hotel.sim.commit(pending)
        elif (hotel.used[t0:stop] + p > self.params.load_target * hotel.cap[t0:stop]).any():
            return self._note(booking, False, "expected rooms exceed the free rooms", p_show=p, min_price=minimum)
        hotel.used[t0:stop] += p
        hotel.raw[t0:stop] += 1
        return self._note(booking, True, "accepted", p_show=p, min_price=minimum, delta=delta)

    def _fallback(self, booking: Mapping) -> bool:
        """Approach A: cautious expected-rooms cap. Used only if decide() errors."""
        try:
            hotel = self.hotels[str(booking["hotel"])]
            t0, stop, nights = hotel.span(booking)
            if not 0 <= t0 < hotel.T or nights <= 0 or not float(booking["nightly_rate"]) > 0:
                return False
            if (hotel.used[t0:stop] + FALLBACK_SHOW_WEIGHT > hotel.cap[t0:stop]).any():
                return False
            hotel.used[t0:stop] += FALLBACK_SHOW_WEIGHT
            hotel.raw[t0:stop] += 1
            return True
        except Exception:
            return False


class SimpleCap:
    """Last-resort policy when the saved bundle cannot be loaded: no overbooking model."""

    def __init__(self, commitments: pd.DataFrame, capacity: dict[str, pd.Series], weight: float = FALLBACK_SHOW_WEIGHT) -> None:
        self.weight = weight
        self.day0 = {str(h): pd.DatetimeIndex(s.index)[0] for h, s in capacity.items()}
        self.cap = {str(h): s.to_numpy(dtype=float) for h, s in capacity.items()}
        self.used = {h: np.zeros(len(c)) for h, c in self.cap.items()}
        for booking in commitments.to_dict(orient="records"):
            self._add(booking, check=False)

    def _add(self, booking: Mapping, check: bool) -> bool:
        hotel = str(booking["hotel"])
        t0 = (pd.Timestamp(booking["arrival_date"]).normalize() - self.day0[hotel]).days
        stop = min(t0 + int(booking["nights"]), len(self.cap[hotel]))
        if not 0 <= t0 < stop:
            return False
        if check and (self.used[hotel][t0:stop] + self.weight > self.cap[hotel][t0:stop]).any():
            return False
        self.used[hotel][t0:stop] += self.weight
        return True

    def decide(self, booking: dict) -> bool:
        try:
            return float(booking["nightly_rate"]) > 0 and self._add(booking, check=True)
        except Exception:
            return False


def save_bundle(directory: str | Path, model, demand: DemandHistory, params: PolicyParams, notes: dict | None = None) -> None:
    """Model, calibrator and preprocessing (model.json + .cbm), price tables, policy settings."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    model.save(directory)
    demand.save(directory / "demand.parquet")
    payload = {"params": asdict(params), "notes": notes or {}}
    (directory / "policy.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_bundle(directory: str | Path):
    from hackathon.cancellation import CancellationModel

    directory = Path(directory)
    params = PolicyParams.from_dict(json.loads((directory / "policy.json").read_text(encoding="utf-8"))["params"])
    return CancellationModel.load(directory), DemandHistory.load(directory / "demand.parquet"), params


def policy_factory(*, demand, model=None, p_show=None, params=None, record=False, holder: list | None = None):
    """Build a Solution-compatible factory for the replay simulator."""
    def factory(commitments, capacity):
        policy = AcceptancePolicy(commitments, capacity, demand=demand, model=model, p_show=p_show,
                                  params=params, record=record)
        if holder is not None:
            holder.append(policy)
        return policy
    return factory
