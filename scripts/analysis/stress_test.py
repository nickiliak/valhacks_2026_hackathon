"""What if the show-up probabilities are wrong in 2017? Greedy vs cautious settings.

Replays January-September 2016 while the policy is fed distorted probabilities:
every p_show is shifted on the log-odds scale before the policy sees it. The
real outcomes are unchanged, so this measures the cost of believing a wrong
model. A negative shift means the policy thinks fewer guests will show than
really do (it overbooks and walks guests); a positive shift means it thinks more
will show (it leaves rooms empty).

uv run python scripts/analysis/stress_test.py artifacts/rolling_2016/p_show.csv
"""

from concurrent.futures import ProcessPoolExecutor
import sys

import numpy as np

from hackathon.experiments import build_stream
from hackathon.policy import PolicyParams

SHIFTS = [-0.6, -0.3, 0.0, 0.3, 0.6]
SETTINGS = {
    "greedy (load 1.1, price 0.85, cap 4)": {"load_target": 1.1, "price_mult": 0.85, "raw_cap": 4.0},
    "default": {},
    "cautious (margin 0.15)": {"margin": 0.15},
    "cautious (shared uncertainty 0.5)": {"logit_noise": 0.5},
}
BENCH = None


def start(source, stream="year"):
    global BENCH
    BENCH = (build_stream(stream, rolling_path=source) if stream == "year"
             else build_stream(stream, model_directory=source))


def run(job):
    name, shift = job
    original = BENCH.p_show
    if shift:
        BENCH.p_show = {k: float(1 / (1 + np.exp(-(np.log(min(max(p, 1e-6), 1 - 1e-6) / (1 - min(max(p, 1e-6), 1 - 1e-6))) + shift))))
                        for k, p in original.items()}
    try:
        result = BENCH.run(PolicyParams.from_dict({**PolicyParams().__dict__, "live_scale": True, **SETTINGS[name]}))
    finally:
        BENCH.p_show = original
    s = result.summary
    return name, shift, s["net_revenue"], s["walks"], s["average_occupancy"]


if __name__ == "__main__":
    rolling = sys.argv[1] if len(sys.argv) > 1 else "artifacts/rolling_2016/p_show.csv"
    if len(sys.argv) > 2:  # optional: comma-separated shifts, e.g. -1.5,-1.2,-0.9
        SHIFTS[:] = [float(v) for v in sys.argv[2].split(",")]
    jobs = [(name, shift) for name in SETTINGS for shift in SHIFTS]
    stream = sys.argv[3] if len(sys.argv) > 3 else "year"  # or s2 / confirm, with a model folder as first argument
    with ProcessPoolExecutor(10, initializer=start, initargs=(rolling, stream)) as pool:
        results = list(pool.map(run, jobs))
    print("Net revenue in EUR million (walks) when the policy's show-up probabilities are shifted.")
    print("A shift of 0.3 moves a 75% show-up chance by about 6 points, 0.6 by about 12 points.")
    print(f"{'settings':38s}" + "".join(f"{('believes fewer show' if s < 0 else 'believes more show' if s > 0 else 'model is right'):>22s}" for s in SHIFTS))
    print(f"{'':38s}" + "".join(f"{s:>+22.1f}" for s in SHIFTS))
    for name in SETTINGS:
        row = [r for r in results if r[0] == name]
        print(f"{name:38s}" + "".join(f"{f'{net / 1e6:.2f} ({walks:,})':>22s}" for _, _, net, walks, _ in row))
        print(f"{'   occupancy':38s}" + "".join(f"{occ:>22.0%}" for *_, occ in row))
