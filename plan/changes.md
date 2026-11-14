# Recommended plan changes

Review date: 14 November 2026.

Status: proposed corrections; the checklist does not mean they have been implemented.

The overall structure is clear: simulator -> preprocessing/CatBoost -> occupancy ledger -> pricing and acceptance -> validation. The missing-value preprocessing is sensible. Address the following before implementing the affected components.

- [ ] **1. Check walking costs across the whole stay.**

  [07_layer2_ledger_and_prices.md](07_layer2_ledger_and_prices.md) checks overflow only on arrival. A guest arriving Monday for two nights can force an already-confirmed Tuesday guest to be walked. Historical minimum prices do not capture that specific penalty.

  Simulate the candidate's effects across affected arrival nights, tracking which guests actually become seated and retain rooms. Account for penalties on already accepted bookings explicitly; use minimum prices to protect capacity for future unknown requests.

- [ ] **2. Make the simulation output consistent with the decision formula.**

  [07_layer2_ledger_and_prices.md](07_layer2_ledger_and_prices.md) calculates net-revenue improvement but calls it a walk cost. [08_layer3_decision_rule.md](08_layer3_decision_rule.md) then subtracts that value from expected revenue. This can reject a profitable booking even in an empty hotel.

  Return `expected_net_revenue_with_candidate - expected_net_revenue_without_candidate` and accept when that improvement exceeds the margin, subject to the other policy checks. Do not subtract the improvement from `p_show * stay_value` again.

- [ ] **3. Correct the fallback overbooking formula.**

  Approach A in [08_layer3_decision_rule.md](08_layer3_decision_rule.md) divides raw bookings by the average show rate. Expected occupancy requires multiplication:

  ```text
  (raw_bookings[t] + 1) * avg_show_rate <= available_capacity[t]
  ```

  Check every stay night, include initial commitments in the booking count, and account for carryover guests through the supplied capacity. At a 50% show rate, the current division formula allows only half the hotel's capacity in bookings.

- [ ] **4. Keep the confirmation period untouched.**

  [06_layer1_show_up_model.md](06_layer1_show_up_model.md) chooses whether to keep calibration using the confirmation period, contradicting [05_validation_and_splits.md](05_validation_and_splits.md).

  Choose raw versus calibrated probabilities on tuning data, freeze the configuration, and evaluate October-December once. Keep calibration fitting separate from model training; use an internal validation period for early stopping and model selection.

- [ ] **5. Define the horizon from the supplied capacity dates.**

  [05_validation_and_splits.md](05_validation_and_splits.md) derives the horizon from the latest initial commitment. Later requests can arrive beyond that date.

  Use each hotel's capacity index as the authoritative supplied horizon. Define consistent handling for stays extending past it in both the policy and simulator.

- [ ] **6. Specify group matching and feature state.**

  The block key in [04_preprocessing.md](04_preprocessing.md) can merge unrelated bookings. Include booking date initially and validate outcome dependence for the actual proposed key, excluding the target from that key.

  Give `block_size_so_far` explicit state. Count every observed request, including rejected requests, and specify whether the current request is included. Use the same ordering and counting convention during training, commitment initialization, and prediction. Keep these counts separate from the accepted-booking ledger.

- [ ] **7. Correct the simulator assertions.**

  [09_simulator.md](09_simulator.md) assumes rejecting all new requests produces zero walks and greedy hindsight beats every strategy. Neither is guaranteed: commitments may already be overbooked, and greedy hindsight is only a lower bound on the optimum.

  Replace these assertions with small deterministic scenarios whose correct scores can be calculated by hand. Treat differences between the two meanings of "cheapest" as measured sensitivity, not an assumption that they must be small.

- [ ] **8. Remove deposit-derived feature-selection reasoning.**

  [CHALLENGE_CONTEXT.md](../CHALLENGE_CONTEXT.md) prohibits deposit-based analysis feeding the solution, but [03_key_insights.md](03_key_insights.md) still uses deposit-recovery results to mandate features.

  Evaluate permitted features directly against `cancelled` using permitted data. Remove requirements and claims justified by reconstructing the unavailable deposit label. The remaining columns can still be used on their own merits.

- [ ] **Build-order adjustment: deliver a working baseline before group simulation.**

  Make group simulation an upgrade after a working CatBoost-plus-ledger baseline, rather than a prerequisite for the first useful submission. Keep the corrected fallback available throughout development and compare each added component through historical replay.
