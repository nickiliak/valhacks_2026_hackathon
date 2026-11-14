"""Replay permitted historical training data; default is S2 tuning only.

Usage: uv run python scripts/replay.py --data data/train.csv

After all settings are frozen, confirmation must preserve July-start policy
state: --start 2016-07-01 --end 2016-12-31 --report-start 2016-10-01.
Never restart the policy in October to measure S2 confirmation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

import pandas as pd

from hackathon.baselines import (
    AcceptAll, CapacityCap, RejectAll, average_rate_factory,
    greedy_hindsight, historical_show_rates,
)
from hackathon.contracts import load_history
from hackathon.simulator import ScoringRules, prepare_replay, replay_prepared, slice_result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/train.csv"))
    parser.add_argument("--start", default="2016-07-01")
    parser.add_argument("--end", default="2016-09-30")
    parser.add_argument("--report-start", help="Report arrivals/nights from this date while retaining earlier replay state")
    parser.add_argument("--cheapest", choices=["both", "stay_value", "nightly_rate"], default="both")
    parser.add_argument("--horizon", choices=["full", "truncate"], default="full")
    parser.add_argument("--output", type=Path, default=Path("artifacts/replay_s2_tuning"))
    args = parser.parse_args()
    if pd.Timestamp(args.end) >= pd.Timestamp("2017-01-01"):
        parser.error("Historical replay must end before 2017")
    data = load_history(args.data)
    args.output.mkdir(parents=True, exist_ok=True)
    readings = ["stay_value", "nightly_rate"] if args.cheapest == "both" else [args.cheapest]
    summaries = []
    for reading in readings:
        prepared = prepare_replay(data, args.start, args.end, rules=ScoringRules(cheapest=reading, horizon=args.horizon))
        rates = historical_show_rates(data, args.start, prepared.rooms)
        policies = {
            "accept_all": AcceptAll, "reject_all": RejectAll,
            "simple_capacity_cap": CapacityCap,
            "average_rate_overbooking": average_rate_factory(rates),
            "greedy_hindsight_lower_bound": None,
        }
        for name, factory in policies.items():
            started = perf_counter()
            result = greedy_hindsight(prepared) if factory is None else replay_prepared(prepared, factory)
            if args.report_start:
                result = slice_result(result, args.report_start)
            summary = {"policy": name, **result.summary, "elapsed_seconds": perf_counter() - started}
            summaries.append(summary)
            prefix = args.output / f"{reading}_{name}"
            result.by_hotel.to_csv(f"{prefix}_hotels.csv", index=False)
            result.by_month.to_csv(f"{prefix}_months.csv", index=False)
            result.decisions.to_csv(f"{prefix}_decisions.csv", index=False)
            result.daily_occupancy.to_csv(f"{prefix}_occupancy.csv", index=False)
            print(f"{reading:12s} {name:28s} net={summary['net_revenue']:,.2f} "
                  f"walks={summary['walks']:,} accept={summary['accept_rate']:.1%} "
                  f"seconds={summary['elapsed_seconds']:.2f}")
    (args.output / "summary.json").write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    pd.DataFrame(summaries).to_csv(args.output / "summary.csv", index=False)


if __name__ == "__main__":
    main()
