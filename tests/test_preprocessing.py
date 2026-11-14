import json
import unittest

import numpy as np
import pandas as pd

from hackathon.preprocessing import (
    CATEGORICAL_FEATURES, FEATURE_COLUMNS, NUMERIC_FEATURES,
    FeatureBuilder, GroupCounter, block_key,
)


def booking(identifier=1, **updates):
    row = {
        "booking_id": identifier, "hotel": "Downtown Hotel", "cancelled": 0,
        "booking_date": "2015-07-01", "arrival_date": "2015-08-01",
        "arrival_month": "August", "arrival_year": 2015, "arrival_day": 1,
        "days_ahead": 31, "nights": 3, "weekend_nights": 1, "weekday_nights": 2,
        "adults": 2, "children": 0, "babies": 0, "country": "PRT",
        "returning_guest": 0, "past_cancellations": 0, "past_stays": 0,
        "sales_segment": "Groups", "sales_channel": "TA/TO", "agent": 304.0,
        "company": None, "guest_type": "Transient", "room_type": "A",
        "meal": "Undefined", "special_requests": 0, "amendments": 0,
        "waitlist_days": 0, "nightly_rate": 100.0,
    }
    row.update(updates)
    return row


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.builder = FeatureBuilder().fit(pd.DataFrame([booking()]))

    def test_training_commitments_and_stream_are_identical(self):
        training = pd.DataFrame([
            booking(3, children=np.nan, company=np.nan),
            booking(1, children=None, company=None),
            booking(2, children=np.nan, company=None),
        ], index=[20, 20, 4])
        expected = self.builder.make_features(training)
        commitments = training.drop(columns="cancelled").copy()
        commitments["booking_date"] = pd.to_datetime(commitments.booking_date)
        commitments["arrival_date"] = pd.to_datetime(commitments.arrival_date)
        commitments["agent"] = "304"
        actual = self.builder.make_features(commitments)
        pd.testing.assert_frame_equal(expected, actual)
        state = GroupCounter()
        streamed = {}
        for row in commitments.sort_values("booking_id").to_dict("records"):
            row["agent"] = 304
            row["company"] = None
            streamed[row["booking_id"]] = self.builder.make_feature_row(row, state)
        as_frame = pd.DataFrame(
            [streamed[row["booking_id"]] for row in training.to_dict("records")],
            index=training.index, columns=FEATURE_COLUMNS,
        )
        for column in CATEGORICAL_FEATURES:
            as_frame[column] = as_frame[column].astype(object)
        pd.testing.assert_frame_equal(expected, as_frame)
        self.assertEqual(list(expected.block_size_so_far), [3, 1, 2])
        self.assertTrue(expected.children.isna().all())
        self.assertTrue((expected.meal == "SC").all())
        self.assertTrue((expected.agent == "304").all())

    def test_future_rows_cannot_change_existing_group_counts(self):
        first = pd.DataFrame([booking(1), booking(2)])
        prefix = self.builder.make_features(first)
        extended = self.builder.make_features(pd.concat([
            first, pd.DataFrame([booking(3), booking(4, booking_date="2015-07-02")]),
        ], ignore_index=True))
        pd.testing.assert_frame_equal(prefix, extended.iloc[:2])
        self.assertEqual(list(extended.block_size_so_far), [1, 2, 3, 1])

    def test_commitment_state_and_rejected_observations_are_counted(self):
        state = GroupCounter()
        self.builder.make_features(pd.DataFrame([booking(1), booking(2)]), state)
        # The caller rejects this row, but observing it still increases demand.
        rejected = self.builder.make_feature_row(booking(3), state)
        accepted = self.builder.make_feature_row(booking(4), state)
        index = FEATURE_COLUMNS.index("block_size_so_far")
        self.assertEqual(rejected[index], 3)
        self.assertEqual(accepted[index], 4)
        self.assertEqual(self.builder.make_features(booking()).block_size_so_far[0], 1)

    def test_fitted_prices_never_depend_on_inference_rows(self):
        self.builder.fit(pd.DataFrame([booking(nightly_rate=80), booking(2, nightly_rate=120)]))
        rows = pd.DataFrame([
            booking(nightly_rate=1000),
            booking(2, nightly_rate=200, arrival_date="2016-01-03"),
            booking(3, hotel="Unseen Hotel", nightly_rate=50),
        ])
        result = self.builder.make_features(rows)
        self.assertEqual(list(result.rate_vs_typical), [10, 2, 0.5])
        self.assertEqual(self.builder.global_rate_median, 100)

    def test_unseen_categories_and_missing_numbers_are_preserved(self):
        row = booking(agent="brand-new-agent", company="new-company", country=None,
                      children=None, nightly_rate=5400, adults=40)
        result = self.builder.make_features(row).iloc[0]
        self.assertEqual(result.agent, "brand-new-agent")
        self.assertEqual(result.company, "new-company")
        self.assertEqual(result.country, "_MISSING_")
        self.assertTrue(np.isnan(result.children))
        self.assertTrue(np.isnan(result.total_guests))
        self.assertTrue(np.isnan(result.has_kids))
        self.assertEqual(result.nightly_rate, 5400)
        self.assertEqual(result.adults, 40)

    def test_allowlist_ignores_target_deposit_and_date_components(self):
        first = booking(deposit="forbidden", cancelled=1, arrival_year=2050)
        second = booking(deposit="changed", cancelled=0, arrival_year=2017)
        pd.testing.assert_frame_equal(
            self.builder.make_features(first), self.builder.make_features(second),
        )
        self.assertFalse({"deposit", "booking_id", "cancelled", "arrival_year", "arrival_day",
                          "booking_date", "arrival_date"} & set(FEATURE_COLUMNS))
        self.assertEqual(len(FEATURE_COLUMNS), len(set(FEATURE_COLUMNS)))

    def test_block_keys_canonicalize_ids_dates_and_missing_values(self):
        first = booking(agent=304.0, nightly_rate=np.nan, booking_date=pd.Timestamp("2015-07-01"))
        second = booking(agent="304.00", nightly_rate=None)
        self.assertEqual(block_key(first), block_key(second))
        changed = booking(agent=304, nightly_rate=None, booking_date="2015-07-02")
        self.assertNotEqual(block_key(first), block_key(changed))

    def test_zero_rate_zero_nights_and_missing_dates(self):
        result = self.builder.make_features(booking(nightly_rate=0, nights=0,
                                                    booking_date=None, arrival_date=None)).iloc[0]
        self.assertEqual(result.is_free, 1)
        self.assertEqual(result.stay_value, 0)
        self.assertTrue(np.isnan(result.weekend_share))
        self.assertTrue(np.isnan(result.arrival_week))
        self.assertEqual(result.arrival_month, "_MISSING_")

    def test_metadata_roundtrip_and_empty_transform(self):
        saved = json.loads(json.dumps(self.builder.to_dict(), allow_nan=False))
        restored = FeatureBuilder.from_dict(saved)
        pd.testing.assert_frame_equal(self.builder.make_features(booking()), restored.make_features(booking()))
        empty = restored.make_features(pd.DataFrame())
        self.assertEqual(list(empty.columns), list(FEATURE_COLUMNS))
        for column in NUMERIC_FEATURES:
            self.assertEqual(empty[column].dtype, np.dtype("float64"))
        self.assertEqual(len(empty), 0)

    def test_requires_fitted_statistics(self):
        with self.assertRaises(RuntimeError):
            FeatureBuilder().make_features(booking())
        with self.assertRaises(ValueError):
            FeatureBuilder().fit(pd.DataFrame())


if __name__ == "__main__":
    unittest.main()
