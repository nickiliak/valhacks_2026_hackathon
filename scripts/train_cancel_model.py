"""Train the cancellation model without opening the final confirmation period.

uv run python scripts/train_cancel_model.py --split S2
"""

import argparse
import json
from pathlib import Path
import time

from hackathon.cancellation import cache_replay_probabilities, train_cancellation_model
from hackathon.contracts import load_history
from hackathon.splits import SPLITS, get_split


def save_calibration_plot(report: dict, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    groups = report["tuning"]["calibration_bins"]
    columns = 3
    rows = (len(groups) + columns - 1) // columns
    figure, axes = plt.subplots(rows, columns, figsize=(12, 3.5 * rows), squeeze=False)
    for axis, (name, bins) in zip(axes.flat, groups.items()):
        axis.plot([0, 1], [0, 1], "--", color="grey", linewidth=1)
        axis.plot([b["mean_p_cancel"] for b in bins], [b["cancel_rate"] for b in bins], "o-")
        axis.set(title=name, xlabel="Predicted cancellation probability", ylabel="Observed cancellation rate",
                 xlim=(0, 1), ylim=(0, 1))
    for axis in list(axes.flat)[len(groups):]:
        axis.set_visible(False)
    figure.suptitle("S2 tuning calibration — July–September 2016")
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="data/train.csv")
    parser.add_argument("--split", choices=list(SPLITS), default="S2")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--layout", choices=["auto", "combined", "per_hotel"], default="auto")
    parser.add_argument("--calibration", choices=["auto", "raw", "sigmoid", "isotonic"], default="auto")
    parser.add_argument("--iterations", type=int, default=800)
    parser.add_argument("--depth", type=int, default=6)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--extend", action="store_true", help="refit the trees on training + calibration months")
    parser.add_argument("--half-life", type=float, help="recency weighting half-life in days")
    args = parser.parse_args()
    destination = args.output or Path("artifacts") / f"cancellation_{args.split.lower()}"
    start = time.perf_counter()
    rows = load_history(args.data)
    purpose = ("October–December is now deployment calibration" if args.split == "Final"
               else "S2 confirmation remains reserved")
    print(f"Training {args.split} on permitted historical data; {purpose}.", flush=True)
    model, report = train_cancellation_model(
        rows, split_name=args.split, layout=args.layout, calibration=args.calibration,
        iterations=args.iterations, depth=args.depth, learning_rate=args.learning_rate,
        seed=args.seed, threads=args.threads, extend=args.extend, half_life=args.half_life,
    )
    report["fit_seconds"] = round(time.perf_counter() - start, 3)
    model.save(destination)
    (destination / "metrics.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    split = get_split(args.split)
    if split.tuning is not None:
        cache_replay_probabilities(rows, split.tuning, destination / "tuning_probabilities.csv",
                                  artifact_directory=destination)
        save_calibration_plot(report, destination / "calibration.png")
    print(json.dumps({"artifact": str(destination), "layout": report["selected_layout"],
                      "calibration": report["selected_calibration"],
                      "tuning_requests": report.get("tuning", {}).get("requests"),
                      "fit_seconds": report["fit_seconds"], "confirmation_evaluated": False}, indent=2))


if __name__ == "__main__":
    main()
