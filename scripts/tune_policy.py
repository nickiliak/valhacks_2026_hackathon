"""Tune policy settings by replaying permitted history. October-December is never reported here.

Two replay streams:
  s2    Jul-Sep 2016, start 1 Jul. The plan's tuning period. Commitments already
        overfill these nights, so it mostly tests "reject nearly everything".
  year  All of 2016 from 1 Jan with rolling, honest probabilities
        (scripts/rolling_probabilities.py); reported for January-September
        arrivals only. This is the 2017 look-alike: few commitments, long leads.

uv run python scripts/tune_policy.py --stream year --set load_target=1.0,1.1 --set margin=0,0.2
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from itertools import product
import json
from pathlib import Path

import pandas as pd

from hackathon.contracts import load_history
from hackathon.experiments import Bench, cached_p_show, line
from hackathon.policy import PolicyParams
from hackathon.splits import Period

BENCH = None


def build(stream: str, data_path: str) -> Bench:
    data = load_history(data_path)
    if stream == "s2":
        p_show = cached_p_show(data, "artifacts/cancellation_s2", Period("2016-07-01", "2017-01-01"))
        return Bench(data, "2016-07-01", "2016-09-30", "2016-07-01", p_show)
    frame = pd.read_csv("artifacts/rolling_2016/p_show.csv")
    return Bench(data, "2016-01-01", "2016-12-31", "2016-01-01", dict(zip(frame.booking_id, frame.p_show)),
                 report=("2016-01-01", "2016-09-30"))


def start(stream: str, data_path: str) -> None:
    global BENCH
    BENCH = build(stream, data_path)


def run(job: tuple[dict, str]) -> dict:
    settings, reading = job
    result = BENCH.run(PolicyParams.from_dict({**PolicyParams().__dict__, **settings}), reading)
    hotels = {f"net_{row.hotel.split()[0].lower()}": row.net_revenue for row in result.by_hotel.itertuples()}
    return {**settings, "reading": reading, **hotels,
            **{k: result.summary[k] for k in ("net_revenue", "revenue", "penalties", "walks", "accept_rate",
                                             "average_occupancy", "seconds")},
            "text": line(json.dumps(settings, separators=(",", ":")) + " " + reading[:4], result)}


def parse(value: str):
    if value in ("None", "none"):
        return None
    if value in ("True", "False"):
        return value == "True"
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stream", choices=["s2", "year"], default="year")
    parser.add_argument("--data", default="data/train.csv")
    parser.add_argument("--set", action="append", default=[], help="name=v1,v2,... (repeatable; full grid)")
    parser.add_argument("--readings", default="stay_value")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--output", type=Path, default=Path("artifacts/tuning"))
    args = parser.parse_args()
    names = [item.split("=")[0] for item in args.set]
    values = [[parse(v) for v in item.split("=")[1].split(",")] for item in args.set]
    jobs = [(dict(zip(names, combo)), reading) for combo in product(*values) for reading in args.readings.split(",")]
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    with ProcessPoolExecutor(min(args.workers, len(jobs)), initializer=start, initargs=(args.stream, args.data)) as pool:
        for row in pool.map(run, jobs):
            print(row.pop("text"), flush=True)
            rows.append({"stream": args.stream, **row})
    path = args.output / f"{args.stream}_results.csv"
    frame = pd.DataFrame(rows)
    if path.exists():
        frame = pd.concat([pd.read_csv(path), frame], ignore_index=True)
    frame.to_csv(path, index=False)


if __name__ == "__main__":
    main()
