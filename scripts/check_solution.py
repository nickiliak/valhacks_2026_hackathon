"""Dress rehearsal for the official run: feed scripts/solution.py a 2017-shaped year.

Uses 2016 as a stand-in: commitments, capacity and requests are built exactly as
the organisers describe them, and the real Solution class decides every request.
It checks that the bundle loads, nothing crashes, odd inputs are survived, and
the run is fast enough.

It prints NO revenue: the Final model was trained on these very 2016 outcomes,
so money from this run would be flattering and meaningless. Use
scripts/simulate.py for honest numbers.

uv run python scripts/check_solution.py
"""

from __future__ import annotations

from pathlib import Path
import sys
from time import perf_counter

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hackathon.contracts import load_history  # noqa: E402
from hackathon.simulator import prepare_replay  # noqa: E402
from solution import Solution  # noqa: E402


def main() -> None:
    data = load_history("data/train.csv")
    prepared = prepare_replay(data, "2016-01-01", "2016-12-31")
    started = perf_counter()
    solution = Solution(prepared.commitments.copy(), {h: s.copy() for h, s in prepared.capacity.items()})
    setup = perf_counter() - started
    print(f"mode: {solution.mode}")
    print(f"set-up: {setup:.1f}s for {len(prepared.commitments):,} commitments")
    if "fallback" in solution.mode:
        raise SystemExit("The bundle did not load. Run: uv run python scripts/build_final.py")
    requests = prepared.requests.to_dict(orient="records")
    started = perf_counter()
    answers = [solution.decide(booking) for booking in requests]
    elapsed = perf_counter() - started
    assert all(isinstance(a, bool) for a in answers)
    print(f"decisions: {len(requests):,} requests in {elapsed:.1f}s ({1000 * elapsed / len(requests):.2f} ms each), "
          f"accepted {np.mean(answers):.1%}")
    print(f"decide() errors that used the fallback rule: {solution.policy.errors}")
    for name, hotel in solution.policy.hotels.items():
        print(f"  {name}: expected rooms used / free rooms, average over the year: "
              f"{(hotel.used / np.maximum(hotel.cap, 1)).mean():.0%}; price scale from commitments {hotel.rate_scale:.2f}")

    # Odd inputs the 2017 feed might contain. None may crash; all must return a bool.
    base = dict(requests[len(requests) // 2])
    last_night = prepared.dates[-1]
    odd = {
        "unseen agent, company and country": {**base, "agent": 987654.0, "company": "NEW", "country": "XXX"},
        "missing values": {**base, "agent": None, "company": float("nan"), "children": None, "country": None, "meal": None},
        "dates as strings": {**base, "arrival_date": str(base["arrival_date"].date()), "booking_date": str(base["booking_date"].date())},
        "numpy scalar types": {**base, "nights": np.int64(base["nights"]), "nightly_rate": np.float32(base["nightly_rate"])},
        "stay running past the last night": {**base, "arrival_date": last_night, "booking_date": last_night, "nights": 9},
        "arrival after the horizon": {**base, "arrival_date": last_night + pd.Timedelta(days=40), "booking_date": last_night},
        "free room": {**base, "nightly_rate": 0.0},
        "unknown hotel": {**base, "hotel": "Airport Hotel"},
        "almost empty dict": {"hotel": base["hotel"]},
    }
    for label, booking in odd.items():
        answer = solution.decide(booking)
        assert isinstance(answer, bool), label
        print(f"  odd input survived: {label:36s} -> {'accept' if answer else 'reject'}")
    print("OK: Solution is ready to hand to evaluate(Solution).")


if __name__ == "__main__":
    main()
