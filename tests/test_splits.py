import unittest

import pandas as pd

from hackathon.splits import Period, get_split, replay_population


class SplitTests(unittest.TestCase):
    def test_boundaries_and_outcomes_known_by_cutoff(self):
        rows = pd.DataFrame({
            "arrival_date": pd.to_datetime(["2016-01-31", "2016-02-01", "2016-03-31",
                                            "2016-04-01", "2016-06-30", "2016-07-01",
                                            "2016-09-30", "2016-10-01", "2016-12-31"]),
            "booking_date": pd.Timestamp("2015-01-01"),
        })
        split = get_split()
        fit, validation = split.training_parts(rows)
        self.assertEqual(list(fit.index), [0])
        self.assertEqual(list(validation.index), [1, 2])
        self.assertEqual(list(split.calibration.select(rows).index), [3, 4])
        self.assertEqual(list(split.tuning.select(rows).index), [5, 6])
        self.assertEqual(list(split.confirmation.select(rows).index), [7, 8])

    def test_commitments_are_not_training_even_if_booked_early(self):
        rows = pd.DataFrame({"booking_id": [3, 2, 1],
                             "booking_date": pd.to_datetime(["2015-01-01", "2016-07-01", "2016-07-01"]),
                             "arrival_date": pd.Timestamp("2016-07-10")})
        self.assertTrue(get_split().train.select(rows).empty)
        commitments, requests = replay_population(rows, Period("2016-07-01", "2016-10-01"))
        self.assertEqual(commitments.booking_id.tolist(), [3])
        self.assertEqual(requests.booking_id.tolist(), [1, 2])


if __name__ == "__main__":
    unittest.main()
