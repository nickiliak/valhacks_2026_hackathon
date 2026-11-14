# 08: Layer 3, the decision rule

## The rule in one sentence
> **Accept if the price beats the night's minimum, the night can take the booking without too much walk risk, and no guardrail says no.**

## In formulas (per hotel; v = rate × nights; p = p_show; t₀ = arrival night)
```
reject if rate == 0                                           (guardrail)
reject if raw_bookings[t] + 1 > cap_k × rooms for any night t of the stay   (guardrail, Insight 5)
reject if rate < mean(min_price[t] for t in stay)             (displacement, 07 tool 3)
accept if p × v − marginal_walk_cost(booking) > margin        (overflow risk, 07 tool 2; margin ≥ 0 = conservative lean)
```
`marginal_walk_cost` already contains the "cheapest guest is bumped" effect; for the cheapest booking of a night it reduces to the 29% rule, for expensive bookings it is much more permissive (Insight 3).

The probability p does **not** appear in the price test (it cancels, Insight 2). It appears in the ledger (how full the night is) and in the risk term.

## Approaches, in build order (A → B → C mandatory; the rest only if time allows)
| # | Approach | Rule | Role |
|---|---|---|---|
| **A** | Rules only | Reject €0; min price per hotel-month from training medians; accept while `raw_bookings / avg_show_rate ≤ rooms` | **Safety-net submission** within the first hour of building. Also the crash fallback |
| **B** | Model + ledger | A, but the ledger uses p_show and the overflow check is block-aware | First real version; expected to beat A clearly |
| **C** | B + minimum prices | Adds fullness-dependent, 2017-scaled min prices | **Main candidate** |
| **E** | Knob tuning | Search cap_k, margin, f-shape, price scale on Jul–Sep 2016; confirm on Oct–Dec | Squeezes the rest; keep knobs to 3–4 |
| **F** | Live adjustment | Scale prices with request flow during the run | Optional hedge against 2017 ≠ 2016 |
| H | Blend | Only if two variants disagree usefully | Optional |
| *dropped* | D (imitate hindsight), G (lookahead per request), I (pure rising bar), full LP duals | Too costly for the day; mention as future work |

## Robustness requirements for `decide()`
- Wrapped in `try/except`; on any error fall back to approach A's rule and log once.
- Handles unseen categories, NaN vs None, floats vs ints, Timestamps vs strings.
- No pandas DataFrame per call. ~44k calls must finish in well under a few minutes; time a full replay.
- Stays past the horizon: treat missing capacity dates as full rooms available, or truncate; be consistent with 09.
- Deterministic (seeded) randomness in the risk simulation.

## Reason codes (for the demo and the interviewer)
Each decision returns, internally, a short list: e.g. `["rate €80 < August minimum €112", "night 94% booked", "show chance 55%"]` and a counterfactual: "accepted at ≥ €112".
