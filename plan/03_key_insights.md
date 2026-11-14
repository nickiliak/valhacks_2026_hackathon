# 03: Key insights that drive the design

These are the conclusions the team reasoned through and agreed. Each one changes what we build. Read slowly; the pitch and the technical interview both rest on them.

## Insight 1: Accepting everyone loses money. Rejecting well is the game.
Rough replay of 2016 (both hotels, our reconstruction of the rules, 2015 in-house guests ignored, every 2016 booking treated as a decision; reproduce with `uv run python scripts/analysis/rough_baselines_2016.py data/train.csv`):

| Strategy | Downtown net | Seaside net | Walks |
|---|---|---|---|
| Accept everyone | **−€715k** | **−€903k** | 10,968 / 6,343 |
| Accept until bookings = rooms (no overbooking) | €2.08M | €1.78M | 0 |
| Overbook using the average show rate | €3.11M | €2.30M | 964 / 303 |
| Perfect hindsight, greedy (a lower bound on the ceiling) | €4.74M | €3.26M | 0 |

Takeaways:
- Walk penalties can exceed all revenue. "No system" is a disaster.
- Even crude overbooking (count each booking as the average show rate) adds ~50% at Downtown over no overbooking. **Accurate accounting of expected rooms is most of the value.**
- The gap to perfect hindsight (~€1.6M Downtown, ~€1M Seaside) is what the model and minimum prices fight for.

## Insight 2: Price decides priority. Probability is only accounting.
For one booking with show probability p:
- expected revenue = p × rate × nights
- expected rooms used = p × nights
- revenue per expected room-night = **rate**. The probability cancels.

So two bookings at the same rate are equally good per room they really use, whatever their cancellation risk. The show-up model's job is **not** to filter out likely cancellers. Its job is to tell the ledger how many rooms a night is *really* using, so we can sell "expected rooms" to the highest rates.

**Rule for the team and the pitch: we never reject a booking *because* it might cancel.** A cancelled booking costs nothing. Rejecting likely cancellers (e.g. "reject if p_cancel > 50%") is the most common mistake on this problem and would throw away revenue.

Where probability *does* matter beyond accounting: risk. A 30%-show booking adds more uncertainty per expected room than a 95%-show booking. That enters through the overflow risk below, not through priority.

No independence assumption is needed for this per-booking identity. Independence only matters when adding bookings up (Insight 4).

## Insight 3: The overflow cost falls on the *cheapest* guest, so the "29% rule" is only right for the cheapest booking.
Classic derivation (one booking, value v, show prob p, q = chance there's no room if it shows, this guest gets walked):
EV = p × [(1 − q) × v − q × 2.5 × v] = p × v × (1 − 3.5q) > 0 ⇔ **q < 1/3.5 ≈ 29%**.

But the rules walk the **cheapest** arriving guest. If our booking is not the cheapest, an overflow bumps someone else worth v_min: we lose their revenue and pay 2.5× their value, total 3.5 × v_min, while still earning v.
EV = p × [v − q × 3.5 × v_min].

Worked example: €400 booking, cheapest arrival that night €100, overflow certain (q = 1): EV = 400 − 350 = **+€50 → accept**. The 29% rule would have rejected it.

Consequences:
- The 29% threshold applies to the cheapest booking of a night; expensive bookings tolerate much higher overflow risk.
- Overbooking penalties land on the smallest values by construction, which makes overbooking cheaper than naive maths suggests.
- Each extra overflow bumps the *next* cheapest guest, so with many accepts the cost climbs. The clean way to evaluate it is a per-night simulation (draw shows, walk the cheapest, measure the change with vs without this booking), not a single threshold.
- Walking happens only at **check-in**. On later nights of a stay the guest is seated and keeps the room; the cost of that is borne by other arrivals and is handled by the minimum price (displacement), not the walk check.

## Insight 4: Group blocks come or cancel together.
31% of rows are duplicates forming 5,553 blocks; 96.5% of blocks share one outcome. A 20-room block at 50% is not "about 10 rooms"; it is **0 or 20**. Summing p × (1 − p) as if independent badly understates the chance of overflow on nights with blocks. In the ledger and the risk simulation, **one coin flip per block**, not per row. Rows of a block arrive consecutively in `decide()` (same booking date), so we can recognise them as they come.

## Insight 5: The `deposit` column is gone; the strongest cancellation signal must come from proxies. Keep guardrails.
Until 12:45 the plan relied on "Non Refund bookings cancel 99.7%". That column is **no longer available** (dropped from the data). What we measured before dropping it: those bookings are 96% PRT, 99.8% with zero special requests, 98.8% inside duplicate blocks, median lead 238 days, concentrated in Groups (46% of Groups rows), Offline TA/TO and a few agents (agent 1: 6,862 rows, 73% cancel). A depth-6 tree identifies them from the remaining columns with AUC 0.76.

Consequences:
- The model will still flag that profile (PRT + no requests + long lead + group/offline + certain agents + in a block) as likely to cancel, but at roughly **70–80%**, not 99.7%. Such bookings count as ~0.2–0.3 of a room instead of ~0. We accept fewer bookings on those nights: **less replay revenue, more robustness**.
- **`country`, `agent`, `sales_segment` and the block feature become the key features.** `block_size_so_far` (04) moves from "if quick" to **required**. Unseen 2017 agents matter more; test that path.
- The old risk "the Non Refund quirk breaks in 2017 and we never notice" is much reduced, because we no longer bet on near-zero probabilities. Drift in ordinary cancel rates (02) remains, and we still get **no feedback during the run**.

Guardrails (all cheap, all kept):
1. **Hard cap on raw bookings per night** regardless of model probabilities (≤ k × rooms, k tuned; start around 2).
2. **Lean conservative on close calls**: a wrong "yes" costs up to 3.5×, a wrong "no" costs 1×.
3. Reject €0 bookings (no upside; they can block later nights of a stay).

## Insight 6: Late bookers are the best customers; hold rooms for them.
See the lead-time table in 02: 0–7 days ahead → ~10% cancel, €100+; a year ahead → 85% cancel, €70. If we fill August in January, we turn away the good customers later. Hence a **minimum price per night** that is higher for busy nights and rises as a night fills (07).

## Insight 7: 2017 will be pricier and busier than 2016; use the commitments as a thermometer.
Same-month rates rose 35–55% from 2015 to 2016. Minimum prices learned from 2016 would be too low for 2017. At start-up our code sees the 2017 commitments; comparing them with the 2016 commitments analog (**like with like**: commitments are long-lead and cheaper than average) gives a scale factor for prices and volume before any decision is made.

## Insight 8: Nationality stays in the model, with a defence ready.
`country` is a strong predictor, and after dropping `deposit` it is the main proxy for the long-lead group blocks that mostly cancel, so removing it would cost more than before. Using nationality to *refuse* service would be discrimination. But under Insight 2 the model never sets priority: a Portuguese guest's booking counts as *fewer* expected rooms, which makes it **easier** to accept, not harder. Rejections happen when a night is full and the rate is too low, whoever the guest is. We also train a version without `country` so we can show the comparison if asked.

## Insight 9: There is no honest full-year test with 18 months of data.
Only Jul–Dec 2016 can be tested with a full 12 months of history behind it (05). We tune on part of it and confirm on the rest. All reported numbers are "our reconstruction of the scorer", stated as such.
