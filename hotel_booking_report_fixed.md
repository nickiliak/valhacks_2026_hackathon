# Hotel Booking Optimisation — Two-slide shareholder pitch

**Format: exactly two slides, five minutes maximum.** Aim to finish at 4:50. Project only the content under “On the slide”; the speaking script and private notes are not additional slides.

## Slide 1 — Earn more from the rooms we already have

**On the slide**

> **Empty rooms lose income. Overbooking can cost even more.**
>
> Learned from **78,132 historical bookings**
>
> **Who will arrive? → What is the room worth? → Does accepting add value?**
>
> Accept when the expected earnings outweigh relocation costs and reservation limits are respected.

**Layout:** Three large boxes for the three questions, connected left to right. Keep the data count as a small supporting line. Explain the booking example aloud; do not add another table or model diagram.

**Speaking script — 0:00–2:50**

*0:00–0:40 — The business problem*

A hotel can have a full reservation book and still have empty rooms. Some guests cancel; others never arrive. But accepting every reservation creates the opposite problem: guests arrive and there is nowhere to put them.

Under this challenge's rules, a stay worth €100 earns us €100 if we provide a room. If we have to relocate that guest, we earn nothing and pay €250. Our goal is to earn more from the rooms we already have, after accounting for those costs.

*0:40–1:35 — What the data changed*

We studied more than 78,000 bookings. They showed that reservations should not all be treated alike. In that history, about 7% of same-day bookings cancelled, compared with 78% of bookings made more than a year ahead.

That led us to estimate each booking's chance of arrival using details such as booking timing, previous cancellations and how the reservation was made. We also found that related bookings often arrive or cancel together, so we consider the risk of a whole group arriving.

Historical prices showed that later reservations can sometimes be worth more. That is why we also consider whether a room is worth keeping for a later offer.

*1:35–2:50 — How a booking becomes a decision*

For each request, we ask the three questions on this slide. Who is likely to arrive? What might these rooms be worth over the guest's stay? And would accepting this reservation improve earnings after relocation costs?

Here is a real example from our historical replay. A guest offered €79 for one night. The system estimated a 71% chance of arrival, but the minimum acceptable price for that night was about €95. It rejected the request because the room was worth protecting for a better offer. We do not change the guest's price; we decide whether to accept it.

When the price is sufficient, we compare possible arrival outcomes with and without that booking, including the cost of relocating this guest or someone already booked. We accept only when the expected gain is positive and our reservation limits are respected. The decision has a business reason a manager can understand.

## Slide 2 — What those decisions delivered

**On the slide**

> **OFFICIAL COMPETITION RESULT**
>
> **[OFFICIAL SCORE + CURRENCY]**
>
> [EXACT METRIC LABEL] · [TEST PERIOD]
>
> ---
>
> **Earlier historical replay — versus average-rate overbooking**
>
> **26% more net revenue · 34% fewer relocated bookings**
>
> October–December 2016. Development replay using our reconstructed scorer; separate from the official result.
>
> **Same rooms. Better booking decisions.**

**Layout:** Give the official score most of the space. Put the historical comparison in a smaller, clearly separated area with a readable label. Keep large revenue tables and prediction metrics off the slide.

**Speaking script — 2:50–4:50**

*2:50–3:20 — The official result*

On the organisers' final test, our solution produced **[OFFICIAL SCORE + CURRENCY]** in **[EXACT METRIC LABEL]**, over **[TEST PERIOD]**. This is the competition result from the new dataset. It is the headline measure of what our booking decisions delivered under the challenge rules.

*3:20–4:15 — Put the improvement in context*

Before that official test, we compared our approach with a simple alternative: overbooking using each hotel's average arrival rate. That baseline allows for cancellations but treats every reservation at the same hotel alike.

In our October-to-December historical replay, for every €100 that baseline earned after relocation penalties, our system earned about €126. At the same time, relocated bookings fell from 436 to 288—about a third fewer.

Those percentages describe our earlier development replay, not the official score above. They show why looking at individual bookings, later demand and relocation costs together was worth pursuing. They do not mean relocations disappear or that the same improvement is guaranteed next year.

*4:15–4:50 — The shareholder takeaway*

For a shareholder, the opportunity is to earn more from existing room capacity while accounting for the cost of letting guests down. For a hotel manager, it is a practical decision on each request: accept a worthwhile booking, protect a valuable room, or avoid an expensive relocation risk.

That is what we built: a system that connects what we learned from past bookings to the value of the next reservation.

---

## Private preparation notes — not slides or part of the timed pitch

- **Rehearsal:** The script is about 560 words. Rehearse with the actual speaker and filled score; finish by 4:50, leaving ten seconds for pauses or a handover. If running long, shorten the historical comparison before cutting the decision example.
- **When the official score arrives:** Replace all three placeholders on slide 2 and in its script. Copy the evaluator's metric label. Use “net revenue” only if relocation penalties are deducted; avoid calling it profit because other operating costs are not included. If the score is still pending, show “Awaiting official evaluation” and skip the official-result paragraph.
- **Comparison discipline:** Keep the 26% / 34% figures explicitly historical. Replace them with an official comparison only if the same baseline was evaluated on the same official data and rules. Never calculate an uplift using the official score and a historical baseline. No extra results slide is needed.
- **If asked how it works:** A CatBoost model estimates arrival probabilities. A separate decision policy considers room use, later demand and relocation costs across possible outcomes. There is no automatic rejection threshold based solely on cancellation risk. The arrival model stays fixed during evaluation; price estimates adjust as requests arrive.
- **If asked what drives predictions:** The fitted model's largest overall signals include country, previous cancellations, booking agent, advance booking time, guest type and sales segment. Special requests and observed group size also contribute. These are statistical associations, not fixed acceptance rules or causal explanations.
- **If asked about validation:** The Q4 replay used a saved model trained on outcomes before July, with policy state continuing from July. Q4 had already been inspected during development, so it is not an untouched confirmation. The deployed model later used all available 2015–2016 history. The official new-data score is reported separately.
- **Historical figures:** €1,348,062 net versus €1,068,190 for average-rate overbooking; relocations 288 versus 436. A stricter capacity-limit baseline had fewer relocations, 215, but lower net revenue, €787,100. The 34% reduction applies to average-rate overbooking specifically. Counts refer to relocated room bookings, not every individual traveller.
- **Rules:** No deposit feature or deposit income. The hotels have separate capacities; guests are not transferred between them. Cancellation forecasts and reservation limits reduce uncertainty and exposure; they cannot guarantee no relocations.
- **Evidence:** Historical data in data/train.csv; the booking example is 59941 in artifacts/simulate_q4_development/stay_value_decisions.csv; comparison totals are in that directory's summary.csv. Scoring assumptions are in CHALLENGE_CONTEXT.md.
