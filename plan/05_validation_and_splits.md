# 05: Validation and time splits

## Principles
1. **Split by time, never randomly.** A random split lets the model learn from bookings that happened after the ones it is tested on.
2. **Outcomes must be known at the cut-off.** A booking is a training row only if its `arrival_date` is before the cut-off (cancellation is known by arrival; a no-show is known on arrival day). Bookings made before the cut-off but arriving after are the *commitments* of the replay, not training rows.
3. **Three periods:** train → calibrate (data the model didn't train on) → test (untouched until the end). Knob tuning happens on a part of the test period and is **confirmed on a separate untouched part**. Report the untouched number.

## The honest limitation
We have 18 months (Jul 2015 – Dec 2016). Only **Jul–Dec 2016** can be tested with a full 12 months of history. There is no clean full-year test. S1 below exists to test the simulator, baselines and the model's behaviour on unseen months, not to validate the full system.

## Splits (by arrival date)
| Split | Train | Calibrate | Replay (decisions) | Tune on | Confirm on | Purpose |
|---|---|---|---|---|---|---|
| **S2 (primary)** | Jul 2015 – Mar 2016 | Apr – Jun 2016 | Jul – Dec 2016 | Jul – Sep 2016 | **Oct – Dec 2016** | The only split with every month seen once. Main evidence |
| **S1 (secondary)** | Jul – Oct 2015 | Nov – Dec 2015 | All of 2016 | – | – | Simulator sanity, baselines, model on unseen seasons. Minimum prices unavailable for Jan–Jun, so approach C can't be fully tested here |
| **Final** | Jul 2015 – Sep 2016 | Oct – Dec 2016 | (the real 2017) | – | – | Keep the calibrated model; do **not** refit on all data afterwards (that would invalidate the calibrator) |

Note S1 and S2 overlap (Jul–Dec 2016 in both); a win on both is not two independent pieces of evidence.

## What a replay is (for a test period starting at date T, per hotel)
- **Commitments** = arrivals in the test period with `booking_date < T`. Always accepted.
- **Capacity** = rooms − guests who arrived before T and are still staying on each night.
- **Decisions** = arrivals in the test period with `booking_date ≥ T`, fed to `decide()` in booking-date order.
- **Score** with the simulator (09) using the real `cancelled` outcomes.

## Horizon
Use each hotel's **`capacity` index** (the nights the organisers supply) as the horizon. Not the latest commitment arrival (later requests can arrive beyond it) and not outside knowledge of the dataset's range. Policy and simulator use one convention for stays extending past the last capacity date (08, 09).

## Model checks on the decision-like population
The bookings we decide on are made *during* the year for arrival in that year, so lead times are ≤ ~365 days and mostly shorter; training data has many longer leads. Check calibration separately on bookings with `days_ahead ≤ 365`, per hotel, and per lead-time band.

## Speed for tuning
Compute `p_show` once for every booking in the replay and store it. Then the policy replays are pure numpy and run in seconds, so dozens of knob settings can be tried.
