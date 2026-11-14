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
- **Arrival vs stay:** a guest can only be walked on their arrival night, but a seated guest occupies rooms on every night of the stay and can cause *other* arrivals to be walked later. Tool 2 simulates the whole effect; Tool 3 protects capacity for future unknown requests.

## Tool 2: the candidate's effect on already-accepted bookings, by simulation
Output: **`delta(booking)` = E[net revenue with the candidate] − E[net revenue without it]**, counting only bookings already accepted (commitments + accepted so far). This single number already contains the candidate's own expected revenue, the risk that it is walked, and the walks it causes among others. **It is not a "walk cost" to subtract from p × v again** (that would double count; see 08).

How:
1. Window: start at the candidate's arrival night t₀ from a valid prior occupancy state (in-house guests on t₀ come from earlier arrivals in the same draw, so simulate from the earliest accepted arrival whose stay can still be in house on t₀). Continue past the candidate's last night **until the "with" and "without" occupancy states are identical** (a walked multi-night guest frees rooms after the candidate has left, which changes later nights), with a cap (e.g. 14 nights beyond the stay, or the horizon). A Monday guest seated for two nights can force a Tuesday arrival to be walked, a concrete penalty on a booking we already hold.
2. Draw show/no-show for every accepted booking whose stay touches the window. Version 1: independent coin per booking. **Upgrade (after B works): one coin per block** (Insight 4).
3. Walk through the window night by night: in-house guests keep rooms; arrivals compete for `capacity[t] − in-house`; if short, walk the cheapest arrivals (active "cheapest" reading); walked guests free all their later nights.
4. Net = Σ seated stay values − 2.5 × Σ walked stay values. Do it with and without the candidate on the **same draws**; average over ~200–500 draws.

Speed: cache per-night draws; recompute only for nights whose ledger changed since the last call; vectorise with numpy. Fallback if too slow: arrival-night-only check with a normal approximation of Σp (blocks as units of variance n²p(1−p)).

The simulation covers bookings we already hold. Capacity for **future, unknown** requests is protected by the minimum prices (Tool 3), not by this simulation.

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
- `delta(hotel, booking)` = expected net-revenue improvement from accepting
- `min_price(hotel, t)`
