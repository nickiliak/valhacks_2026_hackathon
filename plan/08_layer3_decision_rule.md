# 08: Layer 3, the decision rule

## The rule in one sentence
> **Accept if the price beats the night's minimum, the night can take the booking without too much walk risk, and no guardrail says no.**

## In formulas (per hotel; v = rate × nights; p = p_show; t₀ = arrival night)
```
reject if rate == 0                                                         (guardrail)
reject if raw_bookings[t] + 1 > cap_k × rooms for any night t of the stay   (guardrail, Insight 5; raw count includes commitments)
reject if rate < mean(min_price[t] for t in stay)                           (protects capacity for future requests, 07 tool 3)
accept if delta(booking) > margin                                           (07 tool 2; margin ≥ 0 = conservative lean)
```
`delta` is the full expected net-revenue change from accepting, simulated against the bookings we already hold. **Do not compute `p × v − delta`**: delta already includes the candidate's own expected revenue; subtracting would reject profitable bookings even in an empty hotel. In an empty hotel delta ≈ p × v > 0 → accept. On a tight night delta includes the walks the candidate causes (3.5 × the cheapest bumped guest, Insight 3), which can make it negative.

The probability p does **not** appear in the price test (it cancels, Insight 2). It appears in the ledger (how full the night is) and inside delta.

## Approaches, in build order (A → B → C mandatory; the rest only if time allows)
| # | Approach | Rule | Role |
|---|---|---|---|
| **A** | Rules only | Reject €0; min price per hotel-month from training medians; accept while `(raw_bookings[t] + 1) × avg_show_rate ≤ capacity[t]` on **every** night t of the stay, where `raw_bookings` includes commitments and `capacity` is the supplied series (carry-over guests already removed). (An earlier draft divided instead of multiplying, which would allow only half the hotel at a 50% show rate) | **Safety-net submission** within the first hour of building. Also the crash fallback |
| **B** | Model + ledger | A, but the ledger uses p_show and acceptance uses `delta` from a simulation with **independent coins per booking** | First real version; expected to beat A clearly |
| **B+** | Block-aware | Same, one coin per group block in the simulation | Upgrade once B works; measure the gain by replay |
| **C** | B(+) + minimum prices | Adds fullness-dependent, 2017-scaled min prices | **Main candidate** |
| **E** | Knob tuning | Search cap_k, margin, f-shape, price scale on Jul–Sep 2016; confirm on Oct–Dec | Squeezes the rest; keep knobs to 3–4 |
| **F** | Live adjustment | Scale prices with request flow during the run | Optional hedge against 2017 ≠ 2016 |
| H | Blend | Only if two variants disagree usefully | Optional |
| *dropped* | D (imitate hindsight), G (lookahead per request), I (pure rising bar), full LP duals | Too costly for the day; mention as future work |

## Robustness requirements for `decide()`
- Wrapped in `try/except`; on any error fall back to approach A's rule and log once.
- Handles unseen categories, NaN vs None, floats vs ints, Timestamps vs strings.
- No pandas DataFrame per call. ~44k calls must finish in well under a few minutes; time a full replay.
- Horizon = the dates in the supplied `capacity[hotel]` index (authoritative). Stays extending past it: use the same convention as the simulator (09); default: nights beyond the index are ignored for capacity checks and the booking's full stay value counts.
- Deterministic (seeded) randomness in the risk simulation.

## Reason codes (for the demo and the interviewer)
Each decision returns, internally, a short list: e.g. `["rate €80 < August minimum €112", "night 94% booked", "show chance 55%"]` and a counterfactual: "accepted at ≥ €112".
