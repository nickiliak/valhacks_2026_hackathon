# 09: The simulator (our reconstruction of `evaluate.py`)

## Why it comes first
The official scorer is locked. Without our own copy we cannot measure anything. Every approach, knob and chart depends on it. A rough version exists at `scripts/analysis/rough_baselines_2016.py` (run: `uv run python scripts/analysis/rough_baselines_2016.py data/train.csv`); it produced the baseline table in 03. The real one adds commitments, in-house guests from before the start date, and rule switches.

## Specification
Input: a `Solution` class with the official interface, a start date T, an end date, the hotel's rooms, the historical bookings with `cancelled`.

Per hotel:
1. Build `commitments` (arrivals in [T, end] with `booking_date < T`, without `cancelled`, dates as Timestamps) and `capacity` (rooms − guests who arrived before T and are still staying, per night).
2. Instantiate `Solution(commitments, capacity)`.
3. For every booking with `booking_date ≥ T` and arrival in [T, end], in `booking_date` order (tie-break by `booking_id`), call `decide(dict_row)` and record the answer.
4. Night by night from T: in-house count = seated guests still staying. Arrivals = accepted (or committed) bookings arriving tonight with `cancelled == 0`. If arrivals > rooms − in-house, walk the **cheapest** arrivals. Seated guests occupy rooms for all their nights. Walked guests free all their nights.
5. Score = Σ stay value of seated − 2.5 × Σ stay value of walked.

## Switches
| Switch | Options | Default |
|---|---|---|
| cheapest = | `nightly_rate` / `stay_value` | stay_value (matches "2.5× their stay value" wording); report both |
| horizon handling (stays past the last capacity date) | count full stay value, ignore nights beyond the index / truncate | count full, ignore beyond (same in 08) |
| walked guest frees later nights | yes / no | yes |

## Outputs per run
Net revenue, revenue, penalties, walks, accept rate, average occupancy, by hotel and by month. Also the per-booking decision log for the demo and for reason-code examples.

## Baselines (always run alongside)
| Baseline | Definition |
|---|---|
| Accept all | `decide` always True |
| Reject all | commitments only |
| Capacity cap | accept while accepted bookings covering every stay night < rooms (**label it "simple capacity cap", not "Hilton today"**; the brief doesn't describe Hilton's current system) |
| Average-rate overbooking | accept while accepted bookings × average show rate < rooms |
| Perfect hindsight | shows only, highest value first, fits all nights (greedy; a lower bound on the true ceiling). If time: LP relaxation for an upper bound |

Rough 2016 numbers (no in-house, all 2016 bookings as decisions): see 03 Insight 1. Expect them to shift once commitments and in-house guests are included; the ordering should not.

## Checks before trusting it
- **Hand-calculable unit scenarios** (the real test): e.g. 3 rooms, 4 arrivals of known values on one night, one in-house guest, one cancellation → assert the exact revenue, penalty and who is walked; a two-night stay that blocks the next night's arrival; a walked guest freeing later nights; a stay past the horizon. Each under both "cheapest" readings.
- Sanity (not assertions): accept-all produces many walks; reject-all yields only commitment revenue (commitments alone *can* already overflow a night, so walks may be non-zero); greedy hindsight is a lower bound on the optimum, so a strategy slightly above it is possible, if unlikely.
- Report the difference between the two "cheapest" readings as measured sensitivity; do not assume it is small.
- A full replay with the real `Solution` runs in minutes, not hours.
