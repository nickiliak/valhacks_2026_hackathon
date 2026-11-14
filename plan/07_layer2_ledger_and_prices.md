# 07: Layer 2, the ledger and the minimum prices

Everything here is **per hotel**. The two hotels share nothing.

## Tool 1: the ledger of expected rooms
For every night t in the horizon:
```
free_rooms[t]      = capacity[t]                       (given at start-up: rooms − 2016 in-house guests)
expected_used[t]   = Σ p_show(b) over accepted bookings b whose stay covers t
                     (commitments scored by the model at start-up + everything accepted since)
raw_bookings[t]    = count of accepted bookings covering t   (for the hard cap, Insight 5)
blocks[t]          = list of (p_show, rooms_in_block, value) for group blocks covering t
```
- A long-lead group-block booking might add ~0.25; a direct, short-lead booking adds ~0.9. **We count probabilities, not bookings.**
- Updated after every accept. Never learns who cancelled.
- **Arrival vs stay:** walks only happen on the arrival night, so the overflow risk check uses arrival night t₀ with in-house guests from earlier arrivals. Later nights of the stay enter through the minimum price (displacement).

## Tool 2: overflow risk, block-aware
P(no free room on night t₀ if this guest shows) and the expected cost of the walk it causes. Compute by **simulation**, not a formula:
1. Draw show/no-show for every accepted booking covering t₀: independent coin per single booking, **one coin per block** (Insight 4).
2. Count in-house + arrivals; if arrivals exceed free rooms, walk the cheapest arrivals (by the active "cheapest" reading).
3. Compare net revenue with and without the candidate booking; average over ~200–500 draws.
This gives `expected_marginal_walk_cost` directly, including the "cheapest guest is bumped" effect (Insight 3). Precompute per night and refresh only when that night's ledger changes, so `decide()` stays fast. A normal approximation of Σp is the fallback if speed is a problem, with blocks as single units of variance n²p(1−p).

## Tool 3: the minimum price per night
Idea: a room-night on a busy August Saturday is worth more than one on a quiet January Tuesday, because selling it cheaply now forfeits a better sale later.

**Simple estimate (chosen over a full linear program for time reasons):** for each past night in the history available at the cut-off, take the guests who actually showed, sort by nightly rate, and record the rate of the 124th (Downtown) / 103rd (Seaside) guest; if fewer than that showed, the minimum is 0. This approximates the "shadow price" of a room that night. It ignores multi-night coupling; acceptable at our timescale.

Then:
1. **Smooth into a pattern** by hotel × week-of-year × weekday (average over available years; fall back to month × weekday where sparse).
2. **Scale for 2017** with the thermometer (Insight 7): ratio of 2017 commitments' rates to 2016 commitments' rates, per hotel and month, compared like with like. Optionally also a volume ratio.
3. **Raise with fullness:** `min_price[t] = pattern[t] × scale × f(expected_used[t] / free_rooms[t])`, with f rising from ~0.5 when empty to ~1.5–2 when at capacity (shape tuned as a knob). Known from online-selection theory as a "rising threshold".
4. **For a stay**, the booking must beat the **average** min_price over its nights (longer stays pay for all the nights they block).

Where history is missing for a season (S1), the pattern falls back to month-level or to 0.

## Optional: live adjustment during the run (approach F)
Track, per hotel and arrival month, the rate and count of requests seen so far in the run vs. the same point last year. Nudge `scale` up or down with damping. Only if time allows; a few lines once the above exists.

## Outputs
- `expected_used[hotel][t]`, `raw_bookings[hotel][t]`, `blocks[hotel][t]`
- `marginal_walk_cost(hotel, booking)`
- `min_price(hotel, t)`
