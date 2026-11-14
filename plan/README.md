# Valhacks 2026 plan: Hilton booking accept/reject system

**Status:** plan agreed by the team on 14 Nov 2026 ~12:30, after one independent review; updated ~12:45 when the `deposit` column was dropped from the data. The full pipeline is now implemented, including the ledger, risk simulation, minimum prices, acceptance policy and `scripts/solution.py`; see the [repository README](../README.md) for commands, results and known weaknesses. Two deviations from this plan: season labels were removed from the model (they hurt out-of-time calibration), and minimum prices come from last year's later-booking guests per night instead of the 124th/103rd show-up rate with a fullness curve. The final version (model trained on the newest months with recency weighting, weekly re-measured price scale, default policy settings) is described with its results in the repository README. Written to be self-contained: everything needed to understand, verify or execute it is in this folder plus the files it points to.

## Read in this order
| File | What it answers |
|---|---|
| [00_glossary.md](00_glossary.md) | Plain-language definitions of every technical term used |
| [01_challenge_and_rules.md](01_challenge_and_rules.md) | The exact task, the scoring rules, the interface our code must implement, agreed assumptions |
| [02_data_overview.md](02_data_overview.md) | What's in `data/train.csv`, column by column, with verified numbers |
| [03_key_insights.md](03_key_insights.md) | The reasoning that drives the design: why price decides and probability is accounting, the corrected overbooking rule, groups, guardrails |
| [04_preprocessing.md](04_preprocessing.md) | How raw rows become model inputs (agreed with the team) |
| [05_validation_and_splits.md](05_validation_and_splits.md) | How we test honestly without the 2017 data |
| [06_layer1_show_up_model.md](06_layer1_show_up_model.md) | The CatBoost show-up probability model |
| [07_layer2_ledger_and_prices.md](07_layer2_ledger_and_prices.md) | The per-night "expected rooms" ledger and minimum prices |
| [08_layer3_decision_rule.md](08_layer3_decision_rule.md) | How it all becomes accept/reject; approaches in priority order |
| [09_simulator.md](09_simulator.md) | Our reconstruction of the official scorer, with baseline numbers |
| [10_pitch.md](10_pitch.md) | Story for business judges, answers for the technical interviewer |
| [11_timeline_and_decisions.md](11_timeline_and_decisions.md) | Who does what by when; decisions taken; open questions |

## The whole plan in ten lines
1. Two independent hotels (Downtown 124 rooms, Seaside 103). In 2017, booking requests arrive one at a time; our code says accept or reject.
2. Score = revenue of guests who show up and get a room − 2.5 × stay value of every guest we had to turn away at check-in ("walk"). Cancelled bookings earn 0, whatever their deposit.
3. Demand from guests who *actually show up* exceeds rooms on most nights. Accepting everyone loses money (net **negative** in our 2016 replay). Rejecting well is how we win.
4. **Never reject a booking because it might cancel.** A cancelled booking costs nothing. Price sets priority; the show-up probability only tells us how many rooms a night is *really* using.
5. Layer 1: a calibrated CatBoost model gives each booking a show-up probability.
6. Layer 2: a per-night ledger of *expected rooms used*, treating group blocks as one bet, plus a minimum price per night that rises as the night fills, scaled to 2017 price levels using the commitments.
7. Layer 3: accept if the price beats the night's minimum and the overflow risk is worth it, where the cost of overflow is 3.5× the value of the **cheapest** guest that night, not this one.
8. Guardrails: a hard cap on raw bookings per night (we get no feedback in 2017, so any broken pattern would go unnoticed), reject €0 bookings, a crash-safe fallback rule.
9. We test by replaying 2016 through our own reconstruction of the scorer, with time-based splits and an untouched confirmation period.
10. Pitch: one worked booking, a bar chart of baselines vs us vs perfect hindsight, what drives cancellations, honest caveats.

## Ground rules
- **No 2017 data, ever.** `test.csv` is locked, and the same data is publicly online; reading it is cheating under the rules in `scripts/solution.py`.
- Run Python with `uv run python ...`; add packages with `uv add <pkg>`. Windows + PowerShell.
- Commits: no AI attribution lines.
