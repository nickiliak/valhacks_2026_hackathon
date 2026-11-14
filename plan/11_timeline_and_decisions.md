# 11: Timeline, decisions, open questions

## Timeline (plan written 12:30; hacking ends 18:30; presentations reportedly 19:00)
| Time | Work | Done when |
|---|---|---|
| 12:30–13:30 | **Simulator** (09) with commitments, in-house, switches; baselines on S2 and S1. `uv add catboost shap` | Baseline table reproduced properly |
| 13:30–14:00 | **Approach A** in `scripts/solution.py`; runs through the simulator | A valid submission exists |
| 13:30–14:45 (parallel) | **Preprocessing** (04) + **model** (06) on S2: CatBoost, calibration, checks, p_show stored for all replay bookings | Calibration plots look honest |
| 14:45–16:00 | **Ledger + block-aware risk + min prices** (07), **approaches B, C** (08) | C beats the average-overbooking baseline on Jul–Sep 2016 |
| 16:00–16:45 | **Tuning (E)** on Jul–Sep, confirm on Oct–Dec; both "cheapest" readings; optional F | Final settings chosen; untouched number recorded |
| 16:45–17:15 | **Final `solution.py`** trained on the Final split; full replay timing; crash tests | Code freeze |
| 17:15–18:30 | Charts from simulator output, SHAP, demo, slides, one timed rehearsal (10) | Pitch ready |

## Team split
| Person | Owns |
|---|---|
| 1 | Simulator → ledger/risk/prices → decision rule → tuning |
| 2 | Preprocessing → model → calibration → SHAP → demo |
| 3 (if any) | Approach A early, then slides from ~15:00, then rehearsal |

## Decisions taken (with reasons)
| Decision | Reason |
|---|---|
| Never reject for cancellation risk alone | p cancels out of revenue-per-room; a cancelled booking costs nothing |
| **Drop `deposit` entirely** (12:45) | Column not available to us; removed from `data/train.csv`; never referenced |
| Raw-bookings cap per night stays | Protects against any pattern breaking in 2017 with no feedback |
| Keep `country` in the model; **no variant without it** (13:05) | Strong predictor; we maximise revenue for the contest. Verbal fairness answer ready: it never sets priority |
| `block_size_so_far` feature is required | Permitted-data evidence: blocks of 10+ cancel 67% vs 25% singles; 90.7% of blocks share one outcome |
| Second review (`changes.md`, ~13:00) applied in full | Two spec bugs fixed (double-counting `delta`; approach A divided instead of multiplied); confirm period kept untouched; horizon from `capacity` index; block key includes `booking_date`; simulator tested with hand-calculable scenarios; block-aware simulation is an upgrade after B works |
| Minimum prices from the 124th/103rd show-up rate, not an LP | Nearly the same number, far cheaper to build and explain |
| Block-aware risk by simulation | 96.5% of blocks share an outcome; independent maths understates overflow |
| S2 is the primary split; tune Jul–Sep, confirm Oct–Dec | The only split with a full year of history; avoids grading our own homework |
| Drop D, G, I, LP for today | Time; mention as future work |
| 2.5× is a fixed knob | It's the scorer's rule; no data on real walk costs |
| GPU not needed | 78k rows; CPU trains in seconds. Bottlenecks are data and time |

## Open questions (ask the organisers today)
1. Presentation time and length; is 19:00 correct?
2. Will the eval-kit password be shared before the end? If so, read `evaluate.py` immediately and lock the "cheapest" reading and horizon handling.
3. How exactly is "cheapest" defined, and is availability checked only at check-in?

## Things to verify during the build
- `make_features` gives identical output via the three paths (04).
- Simulator sanity checks (09).
- A full replay of the final `Solution` runs in minutes.
- `decide()` survives an unseen agent ID, NaN/None mixes, and a stay past the horizon.
