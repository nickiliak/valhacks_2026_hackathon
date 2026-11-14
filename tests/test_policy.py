import unittest

import numpy as np
import pandas as pd

from hackathon.policy import AcceptancePolicy, DemandHistory, PolicyParams, RiskSim, SimpleCap, thermometer
from hackathon.simulator import ScoringRules, _seat


def random_bookings(rng, count, nights_horizon):
    return pd.DataFrame({
        "booking_id": np.arange(count),
        "hotel": "Downtown Hotel",
        "arrival_date": pd.Timestamp("2016-01-01") + pd.to_timedelta(rng.integers(0, nights_horizon, count), unit="D"),
        "nights": rng.integers(1, 6, count),
        "nightly_rate": rng.permutation(count) + 50.0,  # unique, so no ties
    })


class RiskSimTest(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(7)
        self.horizon, self.draws = 20, 6
        self.dates = pd.date_range("2016-01-01", periods=self.horizon)
        self.capacity = self.rng.integers(2, 6, self.horizon)
        self.bookings = random_bookings(self.rng, 90, self.horizon)
        self.shows = self.rng.random((len(self.bookings), self.draws)) < 0.7

    def reference(self, cheapest):
        """Net revenue and occupancy per draw from the scorer reconstruction."""
        nets, occupancy = [], []
        frame = self.bookings.copy()
        frame["stay_value"] = frame.nightly_rate * frame.nights
        for draw in range(self.draws):
            frame["cancelled"] = (~self.shows[:, draw]).astype(int)
            outcomes, occupied, _ = _seat(frame, self.dates, {"Downtown Hotel": pd.Series(self.capacity, index=self.dates)},
                                          ScoringRules(cheapest=cheapest))
            nets.append(outcomes.revenue.sum() - outcomes.penalties.sum())
            occupancy.append(occupied["Downtown Hotel"])
        return np.array(nets), np.array(occupancy)

    def fill(self, sim, cheapest, order, incremental):
        deltas = 0.0
        for i in order:
            row = self.bookings.iloc[i]
            t0 = (row.arrival_date - self.dates[0]).days
            covered = min(t0 + row.nights, self.horizon) - t0
            value = row.nightly_rate * row.nights
            key = value if cheapest == "stay_value" else row.nightly_rate
            if incremental:
                delta, pending = sim.evaluate(t0, covered, key, value, self.shows[i])
                sim.commit(pending)
                deltas += delta
            else:
                sim.add(t0, key, value, covered, self.shows[i])
        if not incremental:
            sim.rebuild()
        return deltas

    def test_matches_scorer_and_incremental_updates_are_exact(self):
        for cheapest in ("stay_value", "nightly_rate"):
            nets, occupancy = self.reference(cheapest)
            bulk = RiskSim(self.capacity, self.draws)
            self.fill(bulk, cheapest, range(len(self.bookings)), incremental=False)
            np.testing.assert_allclose(bulk.net(), nets)
            np.testing.assert_array_equal(bulk.occ, occupancy)
            for tail in (0, 3, 21):  # short tails force the truncated-commit path
                online = RiskSim(self.capacity, self.draws, tail=tail)
                deltas = self.fill(online, cheapest, self.rng.permutation(len(self.bookings)), incremental=True)
                np.testing.assert_array_equal(online.occ, occupancy)
                np.testing.assert_allclose(online.net(), nets)
                if tail == 21:  # full window: the revenue differences add up to the total
                    self.assertAlmostEqual(deltas, nets.mean(), places=2)

    def test_empty_hotel_delta_is_expected_revenue(self):
        sim = RiskSim(np.full(5, 10), 4)
        delta, _ = sim.evaluate(1, 2, 200.0, 200.0, np.array([True, True, False, False]))
        self.assertAlmostEqual(delta, 100.0)

    def test_full_hotel_delta_charges_the_cheapest_guest(self):
        sim = RiskSim(np.full(3, 1), 1)
        sim.add(0, 100.0, 100.0, 1, np.array([True]))
        sim.rebuild()
        delta, _ = sim.evaluate(0, 1, 400.0, 400.0, np.array([True]))
        self.assertAlmostEqual(delta, 400.0 - 3.5 * 100.0)  # plan 03, insight 3
        delta, _ = sim.evaluate(0, 1, 50.0, 50.0, np.array([True]))
        self.assertAlmostEqual(delta, -2.5 * 50.0)


def history():
    rows = []
    for day in range(120):
        for k in range(6):
            arrival = pd.Timestamp("2015-07-01") + pd.Timedelta(days=day)
            rows.append({"hotel": "Downtown Hotel", "booking_date": arrival - pd.Timedelta(days=5 * k),
                         "arrival_date": arrival, "nights": 1,
                         "nightly_rate": 60.0 + 20 * k, "cancelled": int(k == 5)})
    return pd.DataFrame(rows)


class PriceAndPolicyTest(unittest.TestCase):
    def setUp(self):
        self.demand = DemandHistory.from_rows(history(), "2016-01-01")
        self.dates = pd.date_range("2016-08-01", periods=30)
        self.capacity = {"Downtown Hotel": pd.Series(3, index=self.dates)}
        self.commitments = pd.DataFrame(columns=["booking_id", "hotel", "booking_date", "arrival_date", "nights", "nightly_rate"])

    def booking(self, booking_id, rate, lead=20, nights=1, day=10):
        arrival = self.dates[day]
        return {"booking_id": booking_id, "hotel": "Downtown Hotel", "arrival_date": arrival,
                "booking_date": arrival - pd.Timedelta(days=lead), "nights": nights, "nightly_rate": rate,
                "agent": None, "room_type": "A", "sales_segment": "Direct"}

    def policy(self, **settings):
        cache = {i: 1.0 for i in range(100)}
        return AcceptancePolicy(self.commitments, self.capacity, demand=self.demand, p_show=cache,
                                params=PolicyParams(rate_scale=1.0, draws=20, **settings), record=True)

    def test_night_table_only_counts_guests_who_showed(self):
        lead, rate, pooled = self.demand.night_table("Downtown Hotel", self.dates[10])
        self.assertEqual(pooled, 3)
        self.assertEqual(len(rate), 15)           # 5 showing guests on each of 3 comparable nights
        self.assertEqual(rate.max(), 140.0)       # the 160 guest cancelled
        self.assertTrue((np.diff(rate) <= 0).all())

    def test_minimum_price_rises_as_rooms_fill_and_falls_near_arrival(self):
        policy = self.policy()
        hotel = policy.hotels["Downtown Hotel"]
        # 3 rooms; guests still to come pay 140/120/100/80/60 (x3 comparable nights):
        # the fourth-best rate is the first one that no longer fits.
        self.assertEqual(policy.min_price(hotel, 10, lead=30), 80.0)
        hotel.used[10] = 2
        self.assertEqual(policy.min_price(hotel, 10, lead=30), 120.0)
        self.assertEqual(policy.min_price(hotel, 10, lead=1), 0.0)   # only the 60 guest books later

    def test_decisions_follow_price_then_risk(self):
        policy = self.policy()
        self.assertFalse(policy.decide(self.booking(1, 70.0, lead=30)))
        self.assertIn("below minimum price", policy.log[-1]["reason"])
        self.assertTrue(policy.decide(self.booking(2, 130.0, lead=30)))
        self.assertFalse(policy.decide(self.booking(3, 0.0)))
        for i in range(4, 6):
            self.assertTrue(policy.decide(self.booking(i, 150.0, lead=30)))
        # Three certain guests hold the three rooms: a cheaper fourth would be walked.
        self.assertFalse(policy.decide(self.booking(8, 125.0, lead=0)))
        self.assertIn("walk cost", policy.log[-1]["reason"])

    def test_errors_fall_back_instead_of_crashing(self):
        policy = self.policy()
        self.assertIsInstance(policy.decide({"hotel": "Downtown Hotel", "booking_id": 999}), bool)
        self.assertEqual(policy.errors, 1)
        self.assertFalse(SimpleCap(self.commitments, self.capacity).decide({"hotel": "nowhere"}))

    def test_thermometer_compares_like_with_like(self):
        past = history()
        current = past.loc[(past.booking_date < "2015-07-06") & (past.arrival_date >= "2015-07-06")].copy()
        current["arrival_date"] += pd.Timedelta(days=364)
        current["booking_date"] += pd.Timedelta(days=364)
        current["nightly_rate"] *= 1.2
        measured = thermometer(current, past, "2016-07-04", "2016-12-31")["Downtown Hotel"]
        self.assertAlmostEqual(measured["rate"], 1.2, places=6)
        self.assertAlmostEqual(measured["volume"], 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
