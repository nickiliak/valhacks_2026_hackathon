"""Simulate the whole pipeline on permitted history with the settings in config/policy.json.

Streams (all are our reconstruction of the scorer, never 2017 data):
  year     the 2017 look-alike: all of 2016 from 1 Jan, reported for Jan-Sep arrivals
  s2       Jul-Sep 2016 from 1 Jul: commitments already overfill these nights
  confirm  Oct-Dec 2016, previously used for confirmation and now development data.
           Requires --frozen; use a new --output directory to preserve the archive.

uv run python scripts/simulate.py --stream year
uv run python scripts/simulate.py --stream year --set load_target=1.1   # try a change without editing the config

Needs the model and probability files named in config's replay section.
See README.md for commands to recreate the current context-calibrated inputs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from hackathon.baselines import (AcceptAll, CapacityCap, RejectAll, average_rate_factory,
                                 greedy_hindsight, historical_show_rates)
from hackathon.contracts import load_history
from hackathon.experiments import STREAMS, build_stream, line
from hackathon.policy import PolicyParams
from hackathon.simulator import slice_result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stream", choices=list(STREAMS), default="year")
    parser.add_argument("--data", default="data/train.csv")
    parser.add_argument("--config", type=Path, default=Path("config/policy.json"))
    parser.add_argument("--set", action="append", default=[], help="override one setting, e.g. margin=0.1")
    parser.add_argument("--readings", default="stay_value,nightly_rate", help="readings of 'cheapest' to score")
    parser.add_argument("--no-baselines", action="store_true")
    parser.add_argument("--frozen", action="store_true", help="required for --stream confirm")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.stream == "confirm" and not args.frozen:
        parser.error("Historical confirmation replay requires --frozen. It is now development data; use a new --output directory to preserve the archive.")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    settings = config["policy"].copy()
    replay = config.get("replay", {})
    for item in args.set:
        name, value = item.split("=", 1)
        settings[name] = None if value in ("None", "none") else json.loads(value)
    params = PolicyParams.from_dict(settings)
    output = args.output or Path("artifacts") / f"simulate_{args.stream}"
    output.mkdir(parents=True, exist_ok=True)
    bench = build_stream(args.stream, args.data,
                         model_directory=replay.get("s2_model", "artifacts/cancellation_s2"),
                         rolling_path=replay.get("rolling_probabilities", "artifacts/rolling_2016/p_show.csv"))
    print(f"{args.stream}: {STREAMS[args.stream]}")
    first = bench.prepared["stay_value"]
    show_rates = historical_show_rates(load_history(args.data), first.dates[0], first.rooms)
    summaries = []
    for reading in args.readings.split(","):
        print(f"--- cheapest = {reading}")
        runs = {}
        if not args.no_baselines:
            for name, factory in [("accept all", AcceptAll), ("reject all", RejectAll),
                                  ("simple capacity cap", CapacityCap),
                                  ("average-rate overbooking", average_rate_factory(show_rates))]:
                runs[name] = bench.run(reading=reading, factory=factory)
            hindsight = greedy_hindsight(bench.prepared[reading])
            if bench.report:
                hindsight = slice_result(hindsight, *bench.report)
            hindsight.summary["seconds"] = 0.0
            runs["greedy hindsight (lower bound of ceiling)"] = hindsight
        ours = bench.run(params, reading=reading, record=True)
        runs["OUR POLICY"] = ours
        for name, result in runs.items():
            print(line(name, result), flush=True)
            summaries.append({"stream": args.stream, "reading": reading, "policy": name, **result.summary})
        reasons = pd.DataFrame(ours.policy.log)
        decisions = ours.decisions.merge(reasons.drop(columns="accepted"), on="booking_id", how="left")
        decisions.to_csv(output / f"{reading}_decisions.csv", index=False)
        ours.by_month.to_csv(output / f"{reading}_months.csv", index=False)
        ours.by_hotel.to_csv(output / f"{reading}_hotels.csv", index=False)
        ours.daily_occupancy.to_csv(output / f"{reading}_occupancy.csv", index=False)
        counts = reasons.reason.str.replace(r"rate \d+ below minimum price \d+", "rate below minimum price",
                                            regex=True).value_counts()
        print("   decisions over the whole replay:", ", ".join(f"{k}: {v:,}" for k, v in counts.items()))
        print("   by hotel:", "; ".join(
            f"{r.hotel} net {r.net_revenue:,.0f}, {r.walks} walks, occupancy {r.average_occupancy:.0%}"
            for r in ours.by_hotel.itertuples()))
        if ours.policy.errors:
            print(f"   WARNING: decide() fell back {ours.policy.errors} times")
    pd.DataFrame(summaries).to_csv(output / "summary.csv", index=False)
    (output / "settings.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")
    print(f"saved to {output}")


if __name__ == "__main__":
    main()
