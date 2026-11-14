# Hotel booking decisions: two-slide pitch

**Format:** two slides, five minutes maximum. Aim to finish at 4:30. The script below is also in the speaker notes of `hotel_booking_pitch.pptx`. It is about 550 words, roughly 4:20 at a calm pace, which leaves room for pauses and for the official score.

**Clicks.** The slides build as you speak. **[CLICK]** in the script marks each one: five on slide 1, then one to change slide, then two on slide 2. The two amounts on the left of slide 1 appear by themselves.

Files in this folder:

| File | What it is |
|---|---|
| `hotel_booking_pitch.pptx` | The deck. Edit it directly in PowerPoint |
| `hotel_booking_pitch.pdf` | Backup in case PowerPoint misbehaves on the presenting machine |
| `speaker_script.md` | This script and the question-and-answer notes |
| `build_deck.py` | Rebuilds the deck: `uv run --with python-pptx python pitch/build_deck.py`. It overwrites edits made in PowerPoint |
| `add_animations.ps1` | Run by `build_deck.py`: adds the click-by-click reveals using PowerPoint |

## Slide 1: Earn more from the rooms we already have (0:00–2:35)

**The business problem (0:00–0:35)**

A hotel can have a full reservation book and still have empty rooms, because some guests cancel and others never arrive. But accept every reservation and you get the opposite problem: guests arrive and there is nowhere to put them.

Under this challenge's rules, a stay worth 100 euros earns 100 euros if we give the guest a room. If the hotel is full and we have to relocate them, we earn nothing and pay 250. So the question is not how to fill the hotel. It is which bookings to say yes to.

**What the data showed (0:35–0:50)**

**[CLICK]** We studied more than 78,000 past bookings from two hotels. Guests who book at the last minute almost always arrive; most of those who book a year ahead cancel.

**The three questions (0:50–1:45)**

So for every request we ask three questions.

**[CLICK]** First: who will actually arrive? A model trained on those past bookings gives each booking a chance of showing up.

**[CLICK]** Second: what is the room worth? For every night we look at what the guests who booked later paid last year. If higher-paying guests are still likely to book, we hold the room for them.

**[CLICK]** Third: does saying yes pay off? We cannot know who will turn up, so we rehearse the night 200 times on the computer. In each rehearsal some guests arrive and some do not, according to their chances. We add up the money with this booking and without it.

**A real request, walked through the three questions (1:45–2:35)**

**[CLICK]** Here is a real request: two nights at 119 euros a night. We gave this guest a 72% chance of arriving. The minimum price for those nights was 91 euros, so the price was fine. In the rehearsals the booking brought in 170 euros on average, and added 109 euros of relocation risk, because the hotel was nearly full. That leaves the hotel 61 euros better off, so we accepted. The guest did stay.

The hotel still sets its prices; our system only decides which requests to accept. And we never refuse someone just because they might cancel: a cancellation costs nothing.

## Slide 2: Same rooms, better decisions (2:35–4:30)

**Walk the chart from top to bottom (2:35–3:25)**

What did those decisions deliver? We replayed October to December 2016, booking by booking, under the competition's rules.

**[CLICK]** Accepting every booking almost wipes out the income: relocation costs eat nearly all of it. Never overbooking is safe but leaves rooms empty: 0.79 million euros. Standard overbooking accepts extra bookings up to each hotel's usual share of no-shows, treating every guest alike. It earns 1.07 million.

**[CLICK]** Our system earns 1.35 million. For every 100 euros the standard approach makes, ours makes 126. And it relocates a third fewer guests: 288 instead of 436.

**How close to perfect (3:25–3:40)**

A manager who knew in advance exactly who would cancel could have earned about 1.63 million. We reach 83% of that without knowing the future.

**Two honest notes (3:40–4:00)**

Two honest notes. These figures come from our own replay of past bookings, not the official test. And we had already studied these months when we made our last improvements; an earlier version, tested once on months it had never seen, was 18% ahead of standard overbooking.

*If the official score is known, say it here:* On the organisers' 2017 test, our solution scored …

**The takeaway (4:00–4:30)**

For a shareholder, this is more income from rooms the hotels already have, with fewer guests let down. For a hotel manager, every decision comes with a reason they can read.

Same rooms. Better decisions.

---

## Private notes: not part of the timed pitch

**When the official score arrives.** On slide 2, replace "Awaiting official evaluation" in the top-right tile with the score and the organisers' own label for it. Call it net revenue only if relocation penalties are deducted, and never profit. Do not compute an uplift from the official score against a historical baseline: the periods differ.

**If you run long.** Cut "How close to perfect" first, then "What the data showed". Keep the real request; it is what makes the system understandable.

**Figures behind the slides** (`artifacts/simulate_q4_development/summary.csv`, October–December 2016, our reconstruction of the scorer):

| | Net revenue | Relocated |
|---|---|---|
| Accept every booking | €42,368 | 3,873 |
| Never overbook (simple capacity cap) | €787,100 | 215 |
| Standard overbooking (see below) | €1,068,190 | 436 |
| Our system, final version | €1,348,062 | 288 |
| Our system, earlier frozen version, clean test | €1,261,492 | 255 |
| Perfect hindsight (solver, proven optimal) | about €1.63M | 232 |

- 215 relocations happen whatever we do: they come from bookings the hotel had confirmed before our system started. We add 73; standard overbooking adds 221.
- The real request on slide 1 is booking 99512 in `artifacts/simulate_q4_development/stay_value_decisions.csv`: Downtown, two nights from 12 October 2016, booked 97 days ahead at €118.80 a night (€237.60 in total). Show-up chance 71.6%, minimum price €90.90, simulated gain €61.07. Expected income is 71.6% × €237.60 = €170; the remaining €109 is what the rehearsals charged for relocation risk. The guest arrived and was given a room.
- A declined request to mention if asked for one: booking 59941, one night on 4 November 2016 at €79.20. The minimum price for that night was €94.85, so it was refused on price and never reached the rehearsal.
- Where the 72% matters: it is not a pass mark. It sets how much of a room this guest is expected to use, and in the rehearsals this guest turns up in about 72 of every 100, which is why the expected income is €170 and not €238.
- In `data/train.csv`, 7% of same-day bookings (4,298) and 78% of bookings made more than a year ahead (1,781) were cancelled.

**What "standard overbooking" means.** The usual textbook method: take each hotel's average share of guests who show up, and keep accepting bookings until bookings × that share fills the rooms. Every guest of a hotel counts the same, and price plays no part. We measured the share on earlier data only.

**How to explain the 200 rehearsals, if asked**

Picture one night and the pile of bookings we hold for it. We do not know who will come, only each guest's chance. So the computer rehearses the night:

1. For every booking it flips a weighted coin. A guest with a 70% chance turns up in about 70% of rehearsals.
2. It seats whoever turned up. If there are too many, the cheapest are relocated. It adds up the money.
3. It does this 200 times, then 200 times again with the new booking added.
4. If the average money is higher with the new booking, we accept.

A small example to say aloud: "Two rooms. We hold two bookings at 100 euros, each a coin toss. A new request comes at 150 euros and is 80% likely to show. Most of the time someone stays home and everyone fits. About one time in five all three arrive and we relocate a 100-euro guest, which costs 350. On average the new booking brings in 120 and costs 70, so we say yes."

It is the same idea as a weather forecast: run many versions of tomorrow, and say how often it rains.

**Likely questions**

| Question | Answer |
|---|---|
| How does it work, technically? | A CatBoost model estimates each booking's chance of arriving. A separate decision rule keeps a per-night count of expected guests, sets a minimum price per night from last year's later bookings, and simulates 200 arrival outcomes with and without the request |
| What drives the predictions? | In order: country, previous cancellations, booking agent, how far ahead the booking was made, guest type and sales segment; then special requests and group size. These are statistical patterns, not acceptance rules |
| Who sets the price? | The hotel, as always. Each request arrives with its rate already set by the channel it came through. We only decide which requests to accept; the minimum price is the lowest rate we say yes to for that night |
| Do you reject people who are likely to cancel? | No. A cancelled booking costs nothing. The probability only tells us how full a night really is |
| How was it validated without the official scorer? | We rebuilt the scorer from the rules and replayed 2016. The model for each replay was trained only on earlier arrivals. One version was frozen and tested once on untouched months: 18% ahead. The final version was chosen on other periods; its October–December figure is a development result |
| Is 26% what Hilton should expect? | No. It is one three-month replay. It shows the direction, not a forecast |
| What if the forecasts are wrong in 2017? | We tested that by feeding the system deliberately wrong probabilities. A 10-point error costs about 7% in one direction and almost nothing in the other. We did not tune the settings to one period |
| Why not overbook more aggressively? | Greedier settings gained 2% when the forecast was right and lost far more when it was badly wrong |
| Why is nationality in the model? | It predicts arrival, and it never sets priority. Rejections come from price and fullness. A guest rated less likely to arrive counts as less of a room, which makes acceptance easier |
| What about deposits? | Not used. The deposit column was not available to us and no deposit income is counted |
| Can the two hotels share guests? | No. Each hotel has its own rooms and its own relocations |
| Does it learn during the year? | The arrival model is fixed. The price level is re-measured every week from the rates guests are asking |
