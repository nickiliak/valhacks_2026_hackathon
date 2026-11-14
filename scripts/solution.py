"""Your team's solution. At the end of the hackathon you pass this class to evaluate(Solution)
from evaluate.py, which creates one Solution and replays every 2017 booking request through it.

RULES -- Downtown Hotel has 124 rooms, Seaside Hotel 103. A guest who shows up earns
nightly_rate x nights. When a hotel is full at check-in, the cheapest arriving guests are
walked: they earn nothing and cost 2.5 x their stay value. A seated guest keeps the room.
Your result is the net revenue: revenue of seated guests - walk penalties.

Reading any 2017 data yourself is cheating.

HOW IT DECIDES (details in src/hackathon/policy.py)
1. A cancellation model gives every booking a show-up probability.
2. A ledger adds those probabilities up per hotel night: expected rooms used.
3. Each night has a minimum price, taken from the guests who stayed on the same
   night a year earlier and booked later than today.
4. A simulation of the scoring rules estimates how net revenue changes if the
   booking is accepted, counting the walks it may cause.
A request is accepted when its rate beats the minimum price and the simulated
revenue change is positive. Nothing here reads 2017 data: the model, the price
tables and the settings in artifacts/final were all built from 2015-2016
(uv run python scripts/build_final.py).
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "artifacts" / "final"
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


class _SimpleCap:
    """Self-contained safety net: each booking counts as 0.75 of a room, no overbooking model."""

    WEIGHT = 0.75

    def __init__(self, commitments: pd.DataFrame, capacity: dict[str, pd.Series]) -> None:
        self.day0 = {str(h): pd.Timestamp(s.index[0]) for h, s in capacity.items()}
        self.cap = {str(h): s.to_numpy(dtype=float) for h, s in capacity.items()}
        self.used = {h: np.zeros(len(c)) for h, c in self.cap.items()}
        for booking in commitments.to_dict(orient="records"):
            try:
                self._add(booking, check=False)
            except Exception:
                pass

    def _add(self, booking: dict, check: bool) -> bool:
        hotel = str(booking["hotel"])
        start = (pd.Timestamp(booking["arrival_date"]).normalize() - self.day0[hotel]).days
        stop = min(start + int(booking["nights"]), len(self.cap[hotel]))
        if not 0 <= start < stop:
            return False
        if check and (self.used[hotel][start:stop] + self.WEIGHT > self.cap[hotel][start:stop]).any():
            return False
        self.used[hotel][start:stop] += self.WEIGHT
        return True

    def decide(self, booking: dict) -> bool:
        return float(booking["nightly_rate"]) > 0 and self._add(booking, check=True)


class Solution:
    def __init__(self, commitments: pd.DataFrame, capacity: dict[str, pd.Series]) -> None:
        """Called once, before 2017 starts.

        commitments  2017 arrivals booked before 2017-01-01. The hotel already confirmed them, so
                     decide() is never called for them. Same columns as train.csv, except:
                     - no cancelled column;
                     - arrival_date and booking_date are already pandas Timestamps, not strings.

        capacity     hotel -> rooms free on each night of 2017 (indexed by date): the rooms minus
                     guests who arrived in 2016 and are still in house.
        """
        try:
            from hackathon.policy import AcceptancePolicy, load_bundle

            model, demand, params = load_bundle(BUNDLE)
            self.policy = AcceptancePolicy(commitments, capacity, demand=demand, model=model, params=params)
            self.mode = "model + ledger + prices + simulation"
        except Exception as error:  # a missing bundle must not sink the official run
            print(f"Solution could not load {BUNDLE}: {error!r}. Using the simple capacity rule.", file=sys.stderr)
            self.policy = _SimpleCap(commitments, capacity)
            self.mode = "simple capacity rule (fallback)"

    def decide(self, booking: dict) -> bool:
        """Called once per 2017 booking request, in booking-date order. `booking` is one row with
        the same columns as commitments, as {column: value}. Return True to confirm the booking,
        False to reject it."""
        try:
            return bool(self.policy.decide(booking))
        except Exception:
            return False
