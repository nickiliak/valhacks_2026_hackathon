# 10: Pitch and explainability

## Audiences
- **Business judges** (sponsor Accenture, scenario Hilton): want a clear story and the money.
- **A technical interviewer**: will probe validation, leakage, and whether the logic is sound.

## State the scoring assumption first
"We score what the challenge scores: revenue from guests who show up and get a room, minus 2.5× the stay value of anyone we have to walk. Deposits are not counted, and deposit type is not in our data."

## The story (≤ 7 slides)
1. **Hilton's dilemma.** Empty rooms from cancellations vs. walking guests at 2.5×. Our replay: accepting everyone is net **negative**.
2. **What counts as revenue.** The rules and our assumptions, in one slide.
3. **How the system thinks.** "Every booking uses a fraction of a room equal to its chance of showing up. We sell those fractions to the highest rates, keep a safety margin because the dice are random, and hold rooms for late, high-paying guests." One diagram: model → ledger → minimum price → decision.
4. **One booking, start to finish.** E.g. online travel agent, 200 days ahead, €80/night, August: show chance 45%, counts as 0.45 room, August minimum €112 → **rejected**; same guest 3 days ahead at €130 → **accepted**. Show reason codes and the counterfactual.
5. **Results.** Bar chart: accept all / capacity cap / average overbooking / ours / perfect hindsight, in € and in walks. State uplift vs the capacity cap in % and €. Label everything "our reconstruction of the scorer".
6. **What drives cancellations.** Five plain-language bars from SHAP: lead time, special requests, booking channel/segment, group blocks, past cancellations. Example finding: "large groups booked far ahead through certain agents, with no special requests, mostly never arrive." "We never reject someone because they might cancel; we just don't count on them."
7. **Risks and next steps.** Drift in 2017 and our guardrails; the 2.5× is a knob; future work: live learning, richer group handling, real walk costs. (Fairness of nationality only if asked; see Q&A.)

Demo: a small script or notebook cell that takes a booking and prints decision + reasons. Keep a screenshot backup.

Vocabulary to use: ADR, RevPAR, overbooking level, hurdle rate / bid price, displacement, walk cost, booking curve, length-of-stay.

## Ready answers for the technical interviewer
| Question | Answer |
|---|---|
| How did you validate without the scorer? | Rebuilt it from the rules with switches for the ambiguous parts; replayed 2016 with real outcomes (09) |
| Why not a random split? | Leaks the future. Time splits; outcomes known at the cut-off; untouched confirm period (05) |
| Are the probabilities trustworthy? | Calibrated on a later period; log loss, Brier, calibration plots per hotel and lead band (06). Drift exists; guardrails cover it |
| Why does cancellation probability not decide acceptance? | Expected revenue ÷ expected rooms = rate; p cancels. p is capacity accounting plus risk (03) |
| Where does the overbooking level come from? | Newsvendor logic with the 2.5× penalty, corrected for "cheapest guest is walked": cost of an overflow is 3.5× the cheapest arrival, evaluated by simulation (03, 07) |
| How are minimum prices set? | Rate of the 124th/103rd most valuable show-up on comparable past nights, scaled to 2017 via the commitments, rising with fullness (07) |
| Groups? | Blocks share outcomes 96.5% of the time; one coin per block in the risk model |
| Leakage? | `country`, `amendments`, `special_requests` are partly post-booking in the source; they are in the 2017 input, so allowed; results reported with and without |
| Why CatBoost? | Native categoricals, strong on tabular data; compared against logistic regression and LightGBM |
| Fairness of nationality? | Used as a predictor of show-up, never as a reason to refuse: it only lowers expected room usage, which makes acceptance easier. Rejections are driven by price and fullness. (Verbal answer; no separate model) |
| Why no deposit feature? | The column is not available to us; the model recovers most of that signal from lead time, channel, agent, special requests and block size |
| 2017 different from 2016? | Commitments thermometer for price/volume; hard cap on raw bookings; conservative margin; optional live adjustment |
| Did you use the public 2017 data? | No. Against the rules; everything is tuned on 2015–16 |
| What's the ceiling? | Perfect-hindsight replay; we report our share of it |
