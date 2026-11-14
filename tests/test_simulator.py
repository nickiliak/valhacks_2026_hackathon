import unittest

import numpy as np
import pandas as pd

from hackathon.baselines import (
    AcceptAll, CapacityCap, RejectAll, average_rate_factory,
    greedy_hindsight, historical_show_rates,
)
from hackathon.simulator import ScoringRules, prepare_replay, replay, replay_prepared, score_accepted, slice_result


HOTEL = "Downtown Hotel"
OTHER = "Seaside Hotel"


def booking(identifier, arrival="2016-07-01", *, booked=None, nights=1,
            rate=100, cancelled=0, hotel=HOTEL):
    return {"booking_id": identifier, "hotel": hotel,
            "booking_date": booked or arrival, "arrival_date": arrival,
            "nights": nights, "nightly_rate": rate, "cancelled": cancelled}


def run(rows, *, rooms=1, start="2016-07-01", end="2016-07-03", rules=None, policy=AcceptAll):
    return replay(pd.DataFrame(rows), policy, start, end, rooms={HOTEL: rooms}, rules=rules)


class SimulatorTests(unittest.TestCase):
    def test_exact_score_with_carryover_and_cancellation_under_both_prices(self):
        rows = [booking(0, "2016-06-30", nights=3, rate=1000),
                booking(1, rate=100), booking(2, rate=200),
                booking(3, rate=300), booking(4, rate=400, cancelled=1)]
        for cheapest in ("stay_value", "nightly_rate"):
            with self.subTest(cheapest=cheapest):
                result = run(rows, rooms=3, rules=ScoringRules(cheapest=cheapest))
                self.assertEqual(result.summary["revenue"], 500)
                self.assertEqual(result.summary["penalties"], 250)
                self.assertEqual(result.summary["net_revenue"], 250)
                self.assertEqual(result.summary["walks"], 1)
                self.assertEqual(result.capacity[HOTEL].tolist(), [2, 2, 3])
                self.assertEqual(result.daily_occupancy.occupied.tolist(), [3, 1, 0])
                statuses = result.decisions.set_index("booking_id").status.to_dict()
                self.assertEqual(statuses, {1: "walked", 2: "seated", 3: "seated", 4: "cancelled"})

    def test_seated_guest_keeps_room_on_later_night(self):
        result = run([booking(1, nights=2, rate=10), booking(2, "2016-07-02", rate=100)])
        self.assertEqual(result.summary["net_revenue"], 20 - 250)
        self.assertEqual(result.daily_occupancy.occupied.tolist(), [1, 1, 0])
        self.assertEqual(result.decisions.status.tolist(), ["seated", "walked"])

    def test_walk_releases_later_nights_and_switch_changes_score(self):
        rows = [booking(1, rate=100), booking(2, nights=3, rate=10),
                booking(3, "2016-07-02", rate=50)]
        result = run(rows)
        self.assertEqual(result.summary["net_revenue"], 150 - 75)
        self.assertEqual(result.decisions.status.tolist(), ["seated", "walked", "seated"])
        counterfactual = run(rows, rules=ScoringRules(walked_guests_release_rooms=False))
        self.assertEqual(counterfactual.summary["net_revenue"], 100 - 75 - 125)

    def test_full_history_warmup_resolves_walks_before_carryover(self):
        # The long June 29 booking was walked by a June 28 guest. Counting all
        # historical show-ups as in-house would incorrectly fill July 1.
        rows = [booking(1, "2016-06-28", nights=2, rate=100),
                booking(2, "2016-06-29", nights=5, rate=10), booking(3)]
        result = run(rows)
        self.assertEqual(result.capacity[HOTEL].tolist(), [1, 1, 1])
        self.assertEqual(result.summary["net_revenue"], 100)

    def test_accepted_set_change_recomputes_later_occupancy(self):
        prepared = prepare_replay(pd.DataFrame([
            booking(1, rate=100), booking(2, nights=3, rate=10),
            booking(3, "2016-07-02", rate=50),
        ]), "2016-07-01", "2016-07-03", rooms={HOTEL: 1})
        without = score_accepted(prepared, [2, 3])
        with_candidate = score_accepted(prepared, [1, 2, 3])
        again_without = score_accepted(prepared, [2, 3])
        self.assertEqual(without.summary["net_revenue"], 30 - 125)
        self.assertEqual(with_candidate.summary["net_revenue"], 150 - 75)
        pd.testing.assert_frame_equal(without.decisions, again_without.decisions)
        pd.testing.assert_frame_equal(without.daily_occupancy, again_without.daily_occupancy)

    def test_cheapest_readings_have_measurably_different_results(self):
        rows = [booking(1, rate=100), booking(2, nights=3, rate=60)]
        by_value = run(rows)
        by_rate = run(rows, rules=ScoringRules(cheapest="nightly_rate"))
        self.assertEqual(by_value.summary["net_revenue"], 180 - 250)
        self.assertEqual(by_rate.summary["net_revenue"], 100 - 450)

    def test_equal_prices_have_stable_booking_id_tie_break(self):
        result = run([booking(2), booking(1)])
        self.assertEqual(result.decisions.set_index("booking_id").loc[1, "status"], "seated")
        self.assertEqual(result.decisions.set_index("booking_id").loc[2, "status"], "walked")

    def test_horizon_full_value_or_truncated_nights(self):
        rows = [booking(1, "2016-07-03", nights=3, rate=100)]
        full = run(rows)
        truncated = run(rows, rules=ScoringRules(horizon="truncate"))
        self.assertEqual(full.summary["net_revenue"], 300)
        self.assertEqual(truncated.summary["net_revenue"], 100)
        self.assertEqual(full.daily_occupancy.occupied.tolist(), [0, 0, 1])

    def test_one_instance_global_order_and_no_target_in_inputs(self):
        calls, constructors = [], []

        class Spy:
            def __init__(self, commitments, capacity):
                constructors.append(1)
                self.assert_clean(commitments.columns)
                self.assert_clean = Spy.assert_clean
                assert len(capacity) == 2
                assert commitments.booking_id.tolist() == [0]
                assert pd.api.types.is_datetime64_any_dtype(commitments.arrival_date)
                # Policy mutation must not poison the scorer or another replay.
                for values in capacity.values():
                    values[:] = 0

            @staticmethod
            def assert_clean(columns):
                assert "cancelled" not in columns
                assert "deposit" not in columns
                assert "stay_value" not in columns
                assert "committed" not in columns

            def decide(self, row):
                self.assert_clean(row)
                assert isinstance(row["arrival_date"], pd.Timestamp)
                calls.append(row["booking_id"])
                return True

        rows = [booking(3, hotel=OTHER), booking(2),
                booking(5, "2016-07-02", hotel=OTHER),
                booking(0, "2016-07-03", booked="2016-06-01")]
        frame = pd.DataFrame(rows).assign(deposit="forbidden")
        result = replay(frame, Spy, "2016-07-01", "2016-07-03", rooms={HOTEL: 1, OTHER: 1})
        self.assertEqual(constructors, [1])
        self.assertEqual(calls, [2, 3, 5])
        self.assertEqual(result.summary["revenue"], 400)
        self.assertEqual(result.summary["walks"], 0)

    def test_reject_all_preserves_overflowing_commitments(self):
        rows = [booking(1, booked="2016-06-01", rate=100),
                booking(2, booked="2016-06-01", rate=50), booking(3)]
        result = run(rows, policy=RejectAll)
        self.assertEqual(result.summary["net_revenue"], 100 - 125)
        self.assertEqual(result.summary["accepted_requests"], 0)
        self.assertEqual(result.summary["commitments"], 2)

    def test_explicit_initial_state_overrides_warmup(self):
        dates = pd.date_range("2016-07-01", "2016-07-03")
        frame = pd.DataFrame([booking(1)])
        result = replay(frame, AcceptAll, dates[0], dates[-1], rooms={HOTEL: 1},
                        initial_in_house={HOTEL: pd.Series([1, 0, 0], index=dates)})
        self.assertEqual(result.summary["net_revenue"], -250)
        with self.assertRaises(ValueError):
            prepare_replay(frame, dates[0], dates[-1], rooms={HOTEL: 1},
                           initial_in_house={HOTEL: pd.Series([0, 1, 0], index=dates)})

    def test_hotels_never_exchange_capacity(self):
        rows = pd.DataFrame([booking(1), booking(2, rate=50), booking(3, hotel=OTHER)])
        result = replay(rows, AcceptAll, "2016-07-01", "2016-07-01", rooms={HOTEL: 1, OTHER: 10})
        self.assertEqual(result.summary["walks"], 1)
        self.assertEqual(result.summary["net_revenue"], 200 - 125)

    def test_capacity_cap_counts_commitments_on_every_night(self):
        rows = [booking(1, booked="2016-06-01", nights=2, cancelled=1),
                booking(2, "2016-07-02"), booking(3, "2016-07-03")]
        result = run(rows, policy=CapacityCap)
        self.assertEqual(result.decisions.accepted.tolist(), [True, False, True])
        self.assertEqual(result.summary["accept_rate"], 0.5)

    def test_average_rate_uses_only_outcomes_known_before_cutoff(self):
        frame = pd.DataFrame([booking(1, "2016-06-30", cancelled=1),
                              booking(2, "2016-06-30", cancelled=0),
                              booking(3, cancelled=1), booking(4, cancelled=1)])
        rates = historical_show_rates(frame, "2016-07-01", [HOTEL, OTHER])
        self.assertEqual(rates, {HOTEL: 0.5, OTHER: 1.0})
        result = run([booking(1), booking(2), booking(3)], policy=average_rate_factory({HOTEL: 0.5}))
        self.assertEqual(result.summary["accepted_requests"], 2)

    def test_monthly_metrics_sum_to_total_and_empty_period_is_valid(self):
        result = run([booking(1, "2016-07-31"), booking(2, "2016-08-01")],
                     start="2016-07-31", end="2016-08-01")
        self.assertEqual(result.by_month.net_revenue.sum(), result.summary["net_revenue"])
        self.assertEqual(result.by_hotel.net_revenue.sum(), result.summary["net_revenue"])
        empty = run([booking(1, "2016-06-01")])
        self.assertEqual(empty.summary["requests"], 0)
        self.assertEqual(empty.summary["average_occupancy"], 0)

    def test_hindsight_preserves_commitments_and_selects_feasible_best_value(self):
        prepared = prepare_replay(pd.DataFrame([
            booking(1, rate=50), booking(2, rate=100), booking(3, cancelled=1, rate=1000),
        ]), "2016-07-01", "2016-07-03", rooms={HOTEL: 1})
        result = greedy_hindsight(prepared)
        self.assertEqual(result.summary["net_revenue"], 100)
        self.assertEqual(result.summary["walks"], 0)
        self.assertEqual(result.decisions.loc[result.decisions.accepted, "booking_id"].tolist(), [2])

    def test_repeated_policy_runs_are_isolated(self):
        prepared = prepare_replay(pd.DataFrame([booking(1), booking(2)]),
                                  "2016-07-01", "2016-07-03", rooms={HOTEL: 1})
        first = replay_prepared(prepared, CapacityCap)
        replay_prepared(prepared, AcceptAll)
        second = replay_prepared(prepared, CapacityCap)
        pd.testing.assert_frame_equal(first.decisions, second.decisions)

    def test_confirmation_slice_retains_july_policy_state(self):
        rows = [booking(1, "2016-10-01", booked="2016-07-01", rate=100),
                booking(2, "2016-10-01", booked="2016-07-02", rate=200)]
        full = run(rows, end="2016-12-31", policy=CapacityCap)
        confirmation = slice_result(full, "2016-10-01")
        self.assertEqual(confirmation.summary["net_revenue"], 100)
        self.assertEqual(confirmation.summary["replay_start"], "2016-07-01")
        self.assertEqual(confirmation.decisions.accepted.tolist(), [True, False])
        restarted = run(rows, start="2016-10-01", end="2016-12-31", policy=CapacityCap)
        self.assertEqual(restarted.summary["net_revenue"], 200 - 250)
        with self.assertRaises(ValueError):
            slice_result(full, "2016-01-01")

    def test_invalid_inputs_and_nonboolean_decisions_fail_clearly(self):
        with self.assertRaises(ValueError):
            run([booking(1, nights=0)])
        with self.assertRaises(ValueError):
            run([booking(1), booking(1)])

        class Invalid(AcceptAll):
            def decide(self, booking):
                return None

        with self.assertRaises(TypeError):
            run([booking(1)], policy=Invalid)


if __name__ == "__main__":
    unittest.main()
