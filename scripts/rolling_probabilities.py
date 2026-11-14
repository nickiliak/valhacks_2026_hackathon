"""Honest show-up probabilities for a full-2016 replay (the 2017 look-alike).

A replay that starts on 1 Jan 2016 mirrors the real task: few commitments and
year-long lead times. Each 2016 request is scored by a model that was trained
and calibrated only on arrivals before the quarter in which it was booked:

  booked before Apr 2016 (and all commitments) -> train Jul-Oct 2015, calibrate Nov-Dec 2015
  booked Apr-Jun 2016                          -> train Jul 2015-Jan 2016, calibrate Feb-Mar 2016
  booked Jul-Sep 2016                          -> train Jul 2015-Mar 2016, calibrate Apr-Jun 2016
  booked Oct-Dec 2016                          -> train Jul 2015-Jun 2016, calibrate Jul-Sep 2016

No outcome is ever used before its arrival date has passed.

uv run python scripts/rolling_probabilities.py
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from hackathon.cancellation import train_cancellation_model
from hackathon.contracts import load_history, policy_inputs
from hackathon.splits import ChronologicalSplit, Period, replay_population

REPLAY = Period("2016-01-01", "2017-01-01")
QUARTERS = [  # (requests booked before, train, internal validation, calibration)
    ("2016-04-01", Period("2015-07-01", "2015-11-01"), Period("2015-09-01", "2015-11-01"), Period("2015-11-01", "2016-01-01")),
    ("2016-07-01", Period("2015-07-01", "2016-02-01"), Period("2015-12-01", "2016-02-01"), Period("2016-02-01", "2016-04-01")),
    ("2016-10-01", Period("2015-07-01", "2016-04-01"), Period("2016-02-01", "2016-04-01"), Period("2016-04-01", "2016-07-01")),
    ("2017-01-01", Period("2015-07-01", "2016-07-01"), Period("2016-05-01", "2016-07-01"), Period("2016-07-01", "2016-10-01")),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="data/train.csv")
    parser.add_argument("--calibration", default="sigmoid")
    parser.add_argument("--layout", default="combined")
    parser.add_argument("--output", type=Path, default=Path("artifacts/rolling_2016/p_show.csv"))
    args = parser.parse_args()
    rows = load_history(args.data)
    commitments, requests = replay_population(rows, REPLAY)
    population = policy_inputs(pd.concat([commitments, requests]))
    booked = population.booking_date.to_numpy()
    p_cancel = np.full(len(population), np.nan)
    previous = np.datetime64("1900-01-01")
    for index, (until, train, validation, calibration) in enumerate(QUARTERS):
        split = ChronologicalSplit(f"rolling{index + 1}", train, validation, calibration, REPLAY)
        model, report = train_cancellation_model(rows, split=split, layout=args.layout, calibration=args.calibration)
        # Score the whole stream so block sizes are counted exactly as online.
        scores = model.p_cancel(population)
        mask = (booked >= previous) & (booked < np.datetime64(until))
        p_cancel[mask] = scores[mask]
        previous = np.datetime64(until)
        print(f"model {index + 1}: train rows {report['rows']['train']:,}, scored {int(mask.sum()):,} bookings", flush=True)
    assert not np.isnan(p_cancel).any()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"booking_id": population.booking_id.to_numpy(), "p_show": 1 - p_cancel}).to_csv(args.output, index=False)
    print(f"wrote {args.output} ({len(population):,} rows)")


if __name__ == "__main__":
    main()
