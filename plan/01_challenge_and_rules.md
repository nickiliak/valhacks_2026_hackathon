# 01: The challenge and the rules

## The business problem (from `CHALLENGE_CONTEXT.md`)
Hilton gets more reservations than it has rooms. Guests cancel or don't show, leaving rooms empty. Hilton can overbook, but when it runs out of rooms it pays for a room elsewhere at, on average, 2.5× the rate. They want a system that decides **when to accept a reservation**.

Judging:
1. **Performance:** net revenue, computed by the organisers' scorer.
2. **Explainability:** explain to a non-technical stakeholder how the model works and reaches its recommendations. There will **also be a technical interviewer**.

Event: Valhacks 2026, DTU Skylab, organiser BEST Copenhagen, sponsor Accenture. Hacking 10:30–18:30. Presentations reportedly 19:00 (confirm with organisers; also confirm presentation length).

## The scoring rules (from the docstring of `scripts/solution.py`, verbatim)
> RULES -- Downtown Hotel has 124 rooms, Seaside Hotel 103. A guest who shows up earns nightly_rate x nights. When a hotel is full at check-in, the cheapest arriving guests are walked: they earn nothing and cost 2.5 x their stay value. A seated guest keeps the room. Your result is the net revenue: revenue of seated guests - walk penalties.
>
> Reading any 2017 data yourself is cheating.

## The interface our code must implement (`scripts/solution.py`)
```python
class Solution:
    def __init__(self, commitments: pd.DataFrame, capacity: dict[str, pd.Series]) -> None:
        # Called once before 2017 starts.
        # commitments: 2017 arrivals booked before 2017-01-01. Already confirmed; decide() is never
        #   called for them. Same columns as train.csv except: no `cancelled`; dates are Timestamps.
        # capacity: hotel -> pandas Series indexed by date: rooms free each night of 2017
        #   (rooms minus guests who arrived in 2016 and are still in house).
    def decide(self, booking: dict) -> bool:
        # Called once per 2017 booking request, in booking-date order. `booking` has the same
        # columns as commitments, as {column: value}. True = accept, False = reject.
```
The organisers run `evaluate(Solution)` from their `evaluate.py`. We never see `evaluate.py` or `test.csv` (both in the locked `challenge_files/evaluation-kit.7z`; `test.csv` is ≈6 MB, roughly 40k rows).

## What the rules imply (our reading)
1. The scorer walks through 2017 night by night, per hotel. In-house guests keep rooms. Arriving guests who didn't cancel need a free room. If there aren't enough, the **cheapest** arrivals are walked.
2. A walked guest earns 0 and costs 2.5 × (their nightly_rate × nights). Relative to seating them, walking costs 3.5× their stay value (lost revenue + penalty).
3. **A cancelled booking has no effect on the score.** It never takes a room and is never walked.
4. Walking happens only at **check-in** (the arrival night). On later nights a seated guest keeps the room, which means *other* arriving guests may get walked instead.
5. **Our code gets no feedback** during the run: it never learns who cancelled.

## Agreed assumptions (team decisions, also recorded in `CHALLENGE_CONTEXT.md`)
- **Deposit type does not affect profit.** A cancelled booking earns 0 regardless of deposit.
- **The `deposit` column is not available to us** (team decision, 14 Nov ~12:45). It was dropped from `data/train.csv`. Nothing in the solution may use it. Earlier drafts of this plan leaned on "Non Refund bookings cancel 99.7%"; that signal must now be recovered from other columns (see 03, Insight 5).
- **The two hotels are completely independent.** No moving guests between them. Capacity, overbooking and walks are handled per hotel.
- **The 2.5× is a fixed rule parameter**, not something to predict. The dataset has no record of actual walk costs. In the pitch: "in reality this varies; the system has one knob for it."
- **No 2017 data.** Not for training, tuning, or "just to understand". The commitments and the booking requests our code receives *during* the official run are legitimate inputs.

## Points the rules leave unclear (we build switches for each, see 09)
| Unclear | Readings we support |
|---|---|
| "Cheapest" | lowest `nightly_rate` vs lowest stay value (`rate × nights`) |
| Tie-breaking among equal prices / same booking date | arbitrary; our logic must not depend on it |
| Stays running past the last night of the horizon | count full stay value vs truncate |
| Does a walked guest free their later nights? | yes (they never check in); we assume this |
