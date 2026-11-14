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

These findings shaped both parts of our system: we use booking patterns to predict who will arrive, and pricing patterns to decide when a room should be kept for a more valuable booking.

## 3. Cancellation Prediction — CatBoost

Using the patterns identified in our data, we trained **CatBoost**, a machine-learning model using gradient-boosted decision trees, to predict cancellation probabilities.

We compared one combined model against separate models for each hotel. **The combined model performed better.**

We also removed some calendar features that caused overfitting, improving our model's performance.

Finally, we tested different probability calibration methods. **Isotonic calibration performed best.**

Our final prediction model uses **305 CatBoost trees** and achieved:

- **Log loss:** 0.477
- **AUC:** 0.775
- **Predicted cancellation rate:** 24.1%, compared with the actual 24.3%.

We turn each cancellation prediction into a **show-up probability** and use it in our booking decisions.

## 4. Booking Optimization

We then built a decision algorithm that combines these show-up probabilities with room availability and prices to decide which bookings to accept.

It combines three methods:

1. **Occupancy tracking:** Uses predicted show-up probabilities to estimate how many rooms will be occupied, while accounting for groups that arrive or cancel together.
2. **Minimum pricing:** Uses historical demand and prices to protect rooms for potentially more profitable customers booking later.
3. **Monte Carlo simulation:** Runs 200 simulations for each booking, comparing expected revenue and penalties when accepting versus rejecting.

The algorithm accepts bookings when they are expected to increase net revenue and satisfy its safety limits.

## 5. Testing and Results

To check whether these predictions led to better decisions, we tested the complete system on historical bookings from **October–December 2016**.

| Strategy              |    Net revenue | Relocated guests |
| --------------------- | -------------: | ---------------: |
| Simple capacity limit |       €787,100 |              215 |
| Average overbooking   |     €1,068,190 |              436 |
| **Our system**        | **€1,261,492** |          **255** |

Compared with average overbooking, our system achieved:

- **18.1% more net revenue**
- **41.5% fewer relocated guests**
- **€193,302 additional net revenue on that specific period.**

## 6. Conclusion

We combined **CatBoost, occupancy tracking, minimum pricing, and Monte Carlo simulation** to optimize hotel booking decisions.

Our system performed better than basic overbooking strategies in historical simulations. Official 2017 competition results remain untested.
