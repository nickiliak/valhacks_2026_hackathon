# Valhacks 2026 — Hotel Booking Optimisation System

## 1. The Problem

We developed a system that decides whether to **accept or reject hotel reservations** to maximise net revenue.

We used **78,132 historical bookings** from two hotels with 124 and 103 rooms.

When too many guests arrive, the hotel must relocate some of them, paying a penalty of **2.5 times their booking value**.

## 2. Data Analysis

We analyzed historical bookings to identify cancellation patterns.

Our main findings were:

- **Group bookings:** Groups of 10+ rooms cancelled 67% of the time, compared with 25% for individual bookings.
- **Booking timing:** Same-day bookings cancelled as little as 9%, while bookings made over a year ahead cancelled up to 85%.
- **Customer behavior:** Bookings with special requests cancelled 19% of the time, compared with 47% without requests.
- **Prices:** Customers booking closer to arrival generally paid higher nightly rates.

These findings helped us select features for our prediction model.

## 3. Cancellation Prediction — CatBoost

We trained **CatBoost**, a machine-learning model using gradient-boosted decision trees, to predict cancellation probabilities.

We compared one combined model against separate models for each hotel. **The combined model performed better.**

We also removed some calendar features that caused overfitting, improving our model's performance.

Cancellation behaviour changes over time, so we let the model learn from the most recent months as well and gave recent bookings more weight. **This was our largest single improvement.**

Finally, we calibrated the probabilities on later bookings the model had not seen, so that a predicted 30% really means 30%.

Our final prediction model uses **429 CatBoost trees**. Tested on later bookings it had never seen (July–September 2016), this approach achieved:

- **Log loss:** 0.434 (our first version: 0.477)
- **AUC:** 0.818 (our first version: 0.775)
- **Predicted cancellation rate:** 25.6%, compared with the actual 24.3%.

## 4. Booking Optimization

We developed a second component that uses the cancellation predictions to decide which bookings to accept.

It combines three methods:

1. **Occupancy tracking:** Tracks confirmed reservations and estimates how many guests will actually arrive, including groups.
2. **Minimum pricing:** Sets minimum acceptable prices for each night to protect rooms for potentially more profitable customers. The price level is updated every week from what guests are currently asking to pay.
3. **Monte Carlo simulation:** Runs 200 simulations for each booking, comparing expected revenue and penalties when accepting versus rejecting.

The algorithm accepts bookings when they are expected to increase net revenue and satisfy its safety limits.

## 5. Testing and Results

We tested our system on historical bookings from **October–December 2016**.

| Strategy                                  |    Net revenue | Relocated guests |
| ----------------------------------------- | -------------: | ---------------: |
| Simple capacity limit                     |       €787,100 |              215 |
| Average overbooking                       |     €1,068,190 |              436 |
| Our system, first version (clean test)    |     €1,261,492 |              255 |
| **Our system, final version**             | **€1,348,062** |          **288** |
| Perfect hindsight (knows who will cancel) |    about €1.63M |              232 |

215 of the relocations cannot be avoided: they come from bookings the hotel had confirmed before our system started.

**First version, clean test.** We froze the system and ran it once on these months, which had not been used for any decision. Compared with average overbooking it achieved:

- **18.1% more net revenue** (€193,302)
- **41.5% fewer relocated guests**

**Final version.** We then improved the model and the pricing, choosing the changes on other periods (January–September 2016). Compared with average overbooking it achieves:

- **26.2% more net revenue** (€279,872)
- **33.9% fewer relocated guests**
- **about 83% of what perfect hindsight would earn**

October–December had already been looked at by then, so the final version's result is a development check, not a second clean test.

## 6. Conclusion

We combined **CatBoost, occupancy tracking, minimum pricing, and Monte Carlo simulation** to optimize hotel booking decisions.

Our system performed better than basic overbooking strategies in historical simulations. Official 2017 competition results remain untested.
