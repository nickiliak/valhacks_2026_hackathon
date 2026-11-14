# 00: Glossary (plain language)

**Booking request / booking.** One row of data: a person (or one room of a group) asking for a room at one hotel for certain dates.

**Cancelled.** The booking never produced a guest: either cancelled before arrival or a no-show. The `cancelled` column covers both.

**Show up / show.** The guest actually arrives. `p_show` = our estimated probability of that, between 0 and 1.

**Stay value.** `nightly_rate × nights`. What a guest pays if they come and get a room.

**Walk / walked guest.** A guest who arrives but gets no room because the hotel is full. In this competition they earn nothing and cost 2.5 × their stay value.

**Commitments.** 2017 arrivals that were booked before 1 Jan 2017. Already confirmed; our code can't reject them but they use rooms (if they show).

**Capacity (as given to our code).** For each night of 2017, rooms minus guests who arrived in 2016 and are still staying.

**In-house guests.** Guests already occupying rooms on a night because they arrived earlier and are mid-stay. They keep their rooms.

**Overbooking.** Accepting more bookings than rooms, because some will cancel.

**Overflow.** More guests show up on a night than there are free rooms. The excess gets walked.

**Ledger.** Our running tally, per hotel per night, of how many rooms we expect to be used.

**Expected rooms used.** The sum, over accepted bookings covering a night, of each booking's `p_show`. A booking with a 30% show chance counts as 0.3 of a room.

**Minimum price / bid price / hurdle rate.** The lowest nightly rate we accept for a given night. Higher when a night is nearly full or in high season. Industry terms for the same idea: bid price, hurdle rate.

**Displacement.** Accepting one booking means a room is unavailable for a later, possibly better booking. The minimum price is how we charge for that.

**Model.** A program that learns patterns from past examples (bookings with known outcomes) and applies them to new ones.

**CatBoost / LightGBM.** Two libraries that build "gradient-boosted decision trees": hundreds of small yes/no question trees whose votes are combined. Usually the most accurate choice for table data. CatBoost handles text categories (country, agent) natively.

**Logistic regression.** A simpler model where each factor adds or subtracts points and the total becomes a probability. Easy to explain, usually a bit less accurate.

**Feature.** One input column to the model, after cleaning (e.g. `days_ahead`).

**Target.** The column the model learns to predict: `cancelled`.

**Categorical / numeric.** Text labels (country, deposit type) vs numbers (price, nights).

**Calibration.** Whether the model's probabilities are honest: among bookings it rates "30% cancel", about 30% should actually cancel. We multiply probabilities by money, so this matters more than raw accuracy. **Platt/sigmoid** and **isotonic** are two standard methods to correct a model's probabilities using data it wasn't trained on.

**Log loss / Brier score.** Two numbers that measure probability quality (lower is better). Brier = average squared difference between predicted probability and what happened.

**AUC.** A number between 0.5 and 1 measuring how well the model *ranks* risky bookings above safe ones. 0.5 = coin flip. Says nothing about calibration.

**Calibration plot.** A chart: predicted probability on the x-axis, actual rate on the y-axis. A perfect model is a diagonal line.

**SHAP.** A method that splits one prediction into contributions per feature ("booked 300 days ahead: +25 points towards cancel"). Used for charts of what drives cancellations and for explaining one decision.

**Leakage.** When the model accidentally learns from information it wouldn't have at decision time (e.g. the future). Makes test results look better than reality.

**Out-of-time / time-based split.** Training on earlier dates and testing on later dates, as the real task works. The opposite of a random split.

**Replay / simulator.** Our program that feeds past bookings to our decision code in booking order and computes the money using the official rules and the real outcomes.

**Baseline.** A simple strategy to compare against: accept everyone, cap at rooms, etc.

**Perfect hindsight / oracle.** A fictional manager who knows who will cancel and picks the best possible set of guests. The ceiling on what any system can earn.

**Group block / duplicate rows.** Several identical rows (same hotel, dates, agent, price) = one group booking several rooms. They almost always cancel or show **together**.

**Independence.** The assumption that one guest's cancellation doesn't affect another's. True for strangers, false inside a group block.

**Monte Carlo simulation.** Estimating a probability by running many random scenarios (e.g. flip a weighted coin per booking 500 times and count how often the night overflows).

**Newsvendor ratio.** A classic formula for "how much to overbook": the break-even probability where the expected gain equals the expected penalty. With a 2.5× penalty, 1/(1+2.5) ≈ 29%, but see 03 for why that applies only to the cheapest booking.

**Thermometer (our term).** Using the 2017 commitments, which our code legitimately sees at start-up, to measure how much busier and pricier 2017 is than 2016.

**Knob / hyper-parameter.** A setting we choose by hand or by search (e.g. the overbooking safety margin).

**ADR.** Average daily rate = room revenue ÷ rooms sold. **RevPAR.** Revenue per available room = ADR × occupancy. Hotel industry terms for the pitch.
