import unittest

import numpy as np

from hackathon.policy import RiskSim


class LongStayOccupancyTest(unittest.TestCase):
    def assert_matches_rebuild(self, sim):
        occupancy = sim.occ.copy()
        net = sim.net().copy()
        seats = [seated.copy() for seated in sim.seat]
        sim.rebuild()
        np.testing.assert_array_equal(occupancy, sim.occ)
        np.testing.assert_allclose(net, sim.net())
        for incremental, rebuilt in zip(seats, sim.seat):
            np.testing.assert_array_equal(incremental, rebuilt)

    def test_displaced_long_stay_releases_every_night(self):
        for tail in (0, 3, 21):
            with self.subTest(tail=tail):
                sim = RiskSim(np.ones(100), 1, tail=tail)
                sim.add(1, 69.0, 69.0, 69, np.array([True]))
                sim.rebuild()
                before = sim.occ.copy()

                delta, pending = sim.evaluate(0, 2, 400.0, 400.0, np.array([True]))
                self.assertAlmostEqual(delta, 400.0 - 3.5 * 69.0)
                np.testing.assert_array_equal(sim.occ, before)
                sim.commit(pending)

                expected = np.zeros((1, 100))
                expected[:, :2] = 1
                np.testing.assert_array_equal(sim.occ, expected)
                self.assert_matches_rebuild(sim)

    def test_newly_seated_long_stay_blocks_later_arrival_after_window(self):
        sim = RiskSim(np.ones(100), 1, tail=21)
        sim.add(0, 3.0, 3.0, 3, np.array([True]))
        sim.add(1, 80.0, 80.0, 80, np.array([True]))
        sim.add(75, 100.0, 100.0, 1, np.array([True]))
        sim.rebuild()
        self.assertFalse(sim.seat[1][0, 0])
        self.assertTrue(sim.seat[75][0, 0])
        before_net = sim.net()[0]

        delta, pending = sim.evaluate(0, 1, 400.0, 400.0, np.array([True]))
        # The bounded estimate includes the newly seated 80-night guest, but
        # does not yet charge for displacing the arrival on night 75.
        self.assertAlmostEqual(delta, 400.0 - 3.5 * 3.0 + 3.5 * 80.0)
        sim.commit(pending)

        expected = np.zeros((1, 100))
        expected[:, :81] = 1
        np.testing.assert_array_equal(sim.occ, expected)
        self.assertFalse(sim.seat[75][0, 0])
        self.assertAlmostEqual(sim.net()[0] - before_net, delta - 3.5 * 100.0)
        self.assert_matches_rebuild(sim)


if __name__ == "__main__":
    unittest.main()
