"""Context calibration checks use synthetic rows, never holdout outcomes."""

import json
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from hackathon.calibration import ContextCalibrator


def fixture():
    rng = np.random.default_rng(53)
    size = 720
    rows = pd.DataFrame({
        "hotel": np.where(np.arange(size) % 2, "Seaside Hotel", "Downtown Hotel"),
        "days_ahead": np.tile([0, 7, 8, 30, 31, 90, 91, 180, 181, 365, 366, 450], size // 12),
        "sales_segment": np.tile(["Online TA", "Direct", "Groups"], size // 3),
        "guest_type": np.where(np.arange(size) % 3, "Transient", "Group"),
        "agent": np.tile([9.0, np.nan, 9.0, np.nan, 22.0, 22.0], size // 6),
    })
    raw = rng.uniform(0.02, 0.98, size)
    labels = (rng.random(size) < 0.25 + 0.5 * raw).astype(int)
    return rows, raw, labels


class ContextCalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.raw, cls.labels = fixture()
        cls.calibrator = ContextCalibrator.fit(cls.raw, cls.rows, cls.labels)

    def test_preserves_prototype_features_and_fitted_predictions(self):
        rows, raw = self.rows, self.raw
        hotel = rows.hotel.astype(str)
        band = pd.cut(rows.days_ahead, [-np.inf, 7, 30, 90, 180, 365, np.inf],
                      labels=["0-7", "8-30", "31-90", "91-180", "181-365", "366+"]).astype(str)
        categories = {
            "hotel": hotel, "lead_band": band, "hotel_lead": hotel + "|" + band,
            "hotel_segment": hotel + "|" + rows.sales_segment,
            "guest_type": rows.guest_type,
            "hotel_agent": hotel + "|" + rows.agent.fillna(-1).astype(int).astype(str),
        }
        logit = np.log(raw / (1 - raw)) / 4.0
        seaside = rows.hotel.eq("Seaside Hotel").to_numpy(dtype=float)
        lead = np.log1p(rows.days_ahead.to_numpy()) / np.log(366)
        columns = [np.column_stack([logit, logit * seaside, lead, lead * seaside])]
        for name, values in categories.items():
            counts = values.value_counts()
            levels = sorted(counts[counts >= (100 if name == "hotel_agent" else 30)].index)
            self.assertEqual(self.calibrator.parameters["categories"][name], levels)
            columns.extend((values.to_numpy() == level).astype(float).reshape(-1, 1) for level in levels)
        expected = np.concatenate(columns, axis=1)
        np.testing.assert_array_equal(self.calibrator.design(raw, rows), expected)
        reference = LogisticRegression(C=1.0, max_iter=2000, solver="lbfgs").fit(expected, self.labels)
        np.testing.assert_array_equal(self.calibrator.parameters["coefficient"], reference.coef_[0])
        np.testing.assert_allclose(self.calibrator.transform(raw, rows), reference.predict_proba(expected)[:, 1], atol=1e-15)

    def test_batch_single_missing_unknown_and_agent_identifiers_match(self):
        base = self.rows.iloc[0].to_dict()
        bookings = [{**base, "agent": value} for value in (9, 9.0, "9", "9.0", np.int64(9))]
        bookings += [
            {}, {"hotel": None, "agent": None, "days_ahead": None},
            {"hotel": np.nan, "agent": np.nan, "days_ahead": np.nan},
            {"hotel": pd.NA, "agent": pd.NA, "days_ahead": pd.NA},
            {**base, "hotel": "Airport", "agent": "new-agent", "sales_segment": "New", "guest_type": "New"},
        ]
        bookings += [{**base, "days_ahead": value} for value in (-5, "bad", np.inf, -np.inf, "31")]
        raw = np.full(len(bookings), 0.42)
        expected = self.calibrator.transform(raw, pd.DataFrame(bookings))
        with patch("hackathon.calibration.pd.DataFrame", side_effect=AssertionError("No per-request DataFrame")):
            actual = [self.calibrator.transform_one(p, booking) for p, booking in zip(raw, bookings)]
        np.testing.assert_allclose(expected, actual, atol=1e-15)
        np.testing.assert_array_equal(expected[:5], np.repeat(expected[0], 5))
        np.testing.assert_array_equal(expected[5:9], np.repeat(expected[5], 4))
        self.assertTrue(np.isfinite(actual).all())

    def test_json_roundtrip_preserves_feature_order_even_with_sorted_keys(self):
        saved = json.dumps(self.calibrator.parameters, allow_nan=False, sort_keys=True)
        restored = ContextCalibrator(json.loads(saved))
        np.testing.assert_array_equal(self.calibrator.transform(self.raw, self.rows), restored.transform(self.raw, self.rows))
        booking = self.rows.iloc[0].to_dict()
        self.assertEqual(self.calibrator.transform_one(self.raw[0], booking), restored.transform_one(self.raw[0], booking))

    def test_transform_is_read_only_and_forbidden_columns_are_ignored(self):
        rows = self.rows.copy()
        rows["cancelled"] = "DO_NOT_USE"
        rows["deposit"] = "DO_NOT_USE"
        expected = self.calibrator.transform(self.raw, self.rows)
        np.testing.assert_array_equal(expected, self.calibrator.transform(self.raw, rows))
        fitted = ContextCalibrator.fit(self.raw, rows, self.labels)
        self.assertEqual(fitted.parameters, self.calibrator.parameters)
        snapshot = json.dumps(self.calibrator.parameters, sort_keys=True)
        self.calibrator.transform([0.5], [{"hotel": "ONLY_IN_FUTURE", "agent": "FUTURE_AGENT"}])
        self.assertEqual(json.dumps(self.calibrator.parameters, sort_keys=True), snapshot)
        self.assertNotIn("ONLY_IN_FUTURE", self.calibrator.parameters["categories"]["hotel"])
        self.assertEqual(self.calibrator.parameters["fit_rows"], len(self.rows))

    def test_category_counts_use_only_fitting_rows_and_agent_switch(self):
        rows = self.rows.copy()
        rows["agent"] = np.arange(len(rows))
        rows.loc[:98, "agent"] = 999
        rows["hotel"] = "Downtown Hotel"
        rows.loc[:28, "guest_type"] = "Rare"
        fitted = ContextCalibrator.fit(self.raw, rows, self.labels)
        self.assertNotIn("Downtown Hotel|999", fitted.parameters["categories"]["hotel_agent"])
        self.assertNotIn("Rare", fitted.parameters["categories"]["guest_type"])
        rows.loc[99, "agent"] = 999
        rows.loc[29, "guest_type"] = "Rare"
        fitted = ContextCalibrator.fit(self.raw, rows, self.labels)
        self.assertIn("Downtown Hotel|999", fitted.parameters["categories"]["hotel_agent"])
        self.assertIn("Rare", fitted.parameters["categories"]["guest_type"])
        no_agents = ContextCalibrator.fit(self.raw, rows, self.labels, agents=False)
        self.assertNotIn("hotel_agent", no_agents.parameters["categories"])

    def test_empty_scoring_and_probability_bounds(self):
        self.assertEqual(self.calibrator.transform([], []).shape, (0,))
        self.assertEqual(self.calibrator.transform([], pd.DataFrame()).shape, (0,))
        raw = [-np.inf, -1, 0, 1, 2, np.inf]
        result = self.calibrator.transform(raw, [{} for _ in raw])
        self.assertTrue(((result > 0) & (result < 1)).all())
        np.testing.assert_allclose(result, [self.calibrator.transform_one(p, {}) for p in raw], atol=1e-15)
        for call in (
            lambda: self.calibrator.transform([0.2], []),
            lambda: self.calibrator.transform([np.nan], [{}]),
            lambda: self.calibrator.transform_one(float("nan"), {}),
            lambda: ContextCalibrator.fit([], [], []),
            lambda: ContextCalibrator.fit([0.2, 0.3], [{}, {}], [0, 0]),
        ):
            with self.assertRaises(ValueError):
                call()


if __name__ == "__main__":
    unittest.main()
