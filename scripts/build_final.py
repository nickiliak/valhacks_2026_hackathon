"""Train the deployment model and save everything Solution needs in artifacts/final.

Model: trained on arrivals Jul 2015-Sep 2016, calibrated on Oct-Dec 2016.
Price tables: every 2015-2016 show-up, used as "the same night last year".
Settings: config/policy.json (the same file scripts/simulate.py uses).

uv run python scripts/build_final.py
"""

import argparse
import json
from pathlib import Path
import time

from hackathon.cancellation import train_cancellation_model
from hackathon.contracts import HISTORY_END, load_history
from hackathon.policy import DemandHistory, PolicyParams, save_bundle


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="data/train.csv")
    parser.add_argument("--config", type=Path, default=Path("config/policy.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/final"))
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    started = time.perf_counter()
    rows = load_history(args.data)
    model, report = train_cancellation_model(rows, split_name="Final", layout=config["model"]["layout"],
                                             calibration=config["model"]["calibration"],
                                             extend=config["model"].get("extend", False),
                                             half_life=config["model"].get("half_life"))
    demand = DemandHistory.from_rows(rows, HISTORY_END)
    params = PolicyParams.from_dict(config["policy"])
    save_bundle(args.output, model, demand, params,
                notes={"config": str(args.config), "history_rows": len(rows), "demand_rows": len(demand.frame)})
    (args.output / "metrics.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"bundle": str(args.output), "layout": report["selected_layout"],
                      "calibration": report["selected_calibration"], "train_rows": report["rows"]["train"],
                      "calibration_rows": report["rows"]["calibration"],
                      "seconds": round(time.perf_counter() - started, 1)}, indent=2))


if __name__ == "__main__":
    main()
