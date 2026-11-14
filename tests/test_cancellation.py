"""Small real model checks; no competition confirmation outcomes are evaluated."""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from catboost import CatBoostClassifier
import numpy as np
import pandas as pd

from hackathon.cancellation import (
    CancellationModel, ProbabilityCalibration, cache_replay_probabilities,
    probability_metrics, train_cancellation_model,
)
from hackathon.preprocessing import MODEL_CATEGORICAL, MODEL_FEATURES, FeatureBuilder, GroupCounter
from hackathon.splits import Period


def tiny_history():
    rows = []
    for arrival in ("2015-08-15", "2016-02-15", "2016-05-15", "2016-08-15", "2016-11-15"):
        for hotel in ("Downtown Hotel", "Seaside Hotel"):
            for group in range(4):
                for member in range(4):
                    rows.append({
                        "booking_id": len(rows), "hotel": hotel,
                        "booking_date": pd.Timestamp(arrival) - pd.Timedelta(days=10),
                        "arrival_date": pd.Timestamp(arrival), "days_ahead": 10,
                        "nights": 2 + group % 2, "weekend_nights": 1,
                        "weekday_nights": 1 + group % 2, "adults": 2,
                        "children": None if member == 0 else 0, "babies": 0,
                        "country": "PRT" if group % 2 else "GBR", "returning_guest": 0,
                        "past_cancellations": group % 2, "past_stays": 0,
                        "sales_segment": "Groups", "sales_channel": "TA/TO",
                        "agent": float(group + 100), "company": None,
                        "guest_type": "Transient", "room_type": "A", "meal": "Undefined",
                        "special_requests": 1 - group % 2, "amendments": 0,
                        "waitlist_days": 0, "nightly_rate": 60.0 + 20 * group,
                        "cancelled": group % 2,
                    })
    return pd.DataFrame(rows)


class CancellationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = tiny_history()
        train = cls.rows.loc[cls.rows.arrival_date < "2016-04-01"]
        features = FeatureBuilder().fit(train)
        estimator = CatBoostClassifier(
            iterations=8, depth=2, learning_rate=0.2, random_seed=42, thread_count=1,
            cat_features=list(MODEL_CATEGORICAL), allow_writing_files=False, verbose=False,
        )
        estimator.fit(features.make_features(train)[list(MODEL_FEATURES)], train.cancelled)
        cls.model = CancellationModel(features, {"all": estimator}, metadata={"test_fixture": True})

    def test_batch_matches_commitments_then_stream_with_shared_state(self):
        rows = self.rows.loc[self.rows.arrival_date == "2016-08-15"].copy()
        rows = rows.sample(frac=1, random_state=9)
        expected = self.model.p_cancel(rows)
        ordered = rows.sort_values(["booking_date", "booking_id"])
        state = GroupCounter()
        commitments = ordered.iloc[:2]
        probabilities = dict(zip(commitments.booking_id, self.model.p_cancel(commitments, state=state)))
        for row in ordered.iloc[2:].to_dict("records"):
            row.pop("cancelled")
            row["agent"] = str(int(row["agent"]))
            row["booking_date"] = str(row["booking_date"])
            probabilities[row["booking_id"]] = self.model.p_cancel_one(row, state=state)
        np.testing.assert_allclose(expected, [probabilities[key] for key in rows.booking_id], atol=1e-14)
        self.assertEqual(sum(state.counts.values()), len(rows))
        self.assertEqual(max(state.counts.values()), 4)
        np.testing.assert_allclose(self.model.p_show(rows), 1 - expected)

    def test_empty_prediction_and_unseen_categories(self):
        self.assertEqual(self.model.p_cancel(self.rows.iloc[:0]).shape, (0,))
        self.assertEqual(self.model.p_show(self.rows.iloc[:0]).shape, (0,))
        row = self.rows.iloc[0].to_dict()
        row.update(agent="never-seen-agent", company="new-company", country=None)
        probability = self.model.p_cancel_one(row, state=GroupCounter())
        self.assertTrue(np.isfinite(probability))
        self.assertGreater(probability, 0)
        self.assertLess(probability, 1)

    def test_save_load_preserves_calibrated_probabilities(self):
        calibration = ProbabilityCalibration.fit(
            "sigmoid", [0.1, 0.2, 0.4, 0.6, 0.8, 0.9], [0, 0, 1, 0, 1, 1],
        )
        original = CancellationModel(self.model.features, self.model.models, calibration, {"split": "fixture"})
        with tempfile.TemporaryDirectory() as directory:
            original.save(directory)
            restored = CancellationModel.load(directory)
            np.testing.assert_allclose(original.p_cancel(self.rows), restored.p_cancel(self.rows), atol=1e-14)
            self.assertEqual(restored.metadata, {"split": "fixture"})
            self.assertEqual(restored.calibration.parameters, original.calibration.parameters)

    def test_model_checksum_rejects_changed_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            self.model.save(directory)
            model_file = Path(directory) / "model_0.cbm"
            model_file.write_bytes(model_file.read_bytes() + b"changed")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                CancellationModel.load(directory)

    def test_schema_rejects_changed_feature_order(self):
        with tempfile.TemporaryDirectory() as directory:
            self.model.save(directory)
            manifest_path = Path(directory) / "model.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["feature_columns"] = manifest["feature_columns"][::-1]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "schema"):
                CancellationModel.load(directory)

    def test_schema_rejects_changed_categorical_features(self):
        with tempfile.TemporaryDirectory() as directory:
            self.model.save(directory)
            manifest_path = Path(directory) / "model.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["categorical_features"].remove("agent")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "schema"):
                CancellationModel.load(directory)

    def test_probability_cache_is_label_free_and_population_scoped(self):
        period = Period("2016-08-01", "2016-09-01")
        with tempfile.TemporaryDirectory() as directory:
            self.model.save(directory)
            output = Path(directory) / "predictions.csv"
            first = cache_replay_probabilities(self.rows, period, output, artifact_directory=directory)
            first_manifest = json.loads(output.with_suffix(".manifest.json").read_text())
            self.assertEqual(len(first), 32)
            self.assertFalse({"cancelled", "deposit"} & set(first.columns))
            np.testing.assert_allclose(first.p_show + first.p_cancel, 1)
            expected_hash = hashlib.sha256((Path(directory) / "model.json").read_bytes()).hexdigest()
            self.assertEqual(first_manifest["model_sha256"], expected_hash)
            mutated = self.rows.copy()
            mutated["cancelled"] = 1 - mutated.cancelled
            cache_replay_probabilities(mutated, period, output, artifact_directory=directory)
            second_manifest = json.loads(output.with_suffix(".manifest.json").read_text())
            self.assertEqual(first_manifest["population_sha256"], second_manifest["population_sha256"])
            mutated.loc[mutated.arrival_date == "2016-08-15", "nightly_rate"] += 1
            cache_replay_probabilities(mutated, period, output, artifact_directory=directory)
            changed_manifest = json.loads(output.with_suffix(".manifest.json").read_text())
            self.assertNotEqual(first_manifest["population_sha256"], changed_manifest["population_sha256"])

    def test_training_never_reads_confirmation_labels_or_features(self):
        rows = self.rows.copy()
        confirmation = rows.arrival_date >= "2016-10-01"
        rows["cancelled"] = rows.cancelled.astype(object)
        # Any attempt to fit/score these outcomes would fail integer conversion.
        rows.loc[confirmation, "cancelled"] = "CONFIRMATION_MUST_REMAIN_UNTOUCHED"
        rows.loc[confirmation, "nightly_rate"] = 1e12
        rows.loc[confirmation, "hotel"] = "CONFIRMATION_ONLY_HOTEL"
        model, report = train_cancellation_model(
            rows, layout="combined", calibration="auto", iterations=6, depth=2,
            learning_rate=0.2, seed=17, threads=1,
        )
        self.assertFalse(report["confirmation_evaluated"])
        self.assertEqual(report["rows"]["train"], 64)
        self.assertEqual(report["rows"]["internal_fit"], 32)
        self.assertEqual(report["rows"]["internal_validation"], 32)
        self.assertEqual(report["rows"]["calibration"], 32)
        self.assertEqual(report["tuning"]["requests"]["rows"], 32)
        self.assertNotIn("CONFIRMATION_ONLY_HOTEL", model.features.hotel_rate_medians)
        self.assertLess(model.features.global_rate_median, 1000)
        self.assertEqual(set(report["calibration_candidates"]), {"raw", "sigmoid"})

    def test_final_split_requires_frozen_calibration_choice(self):
        with self.assertRaisesRegex(ValueError, "frozen"):
            train_cancellation_model(self.rows, split_name="Final", calibration="auto", iterations=2)


class CalibrationTests(unittest.TestCase):
    def test_all_methods_roundtrip_and_stay_bounded(self):
        probabilities = [0.01, 0.1, 0.2, 0.3, 0.5, 0.6, 0.8, 0.9]
        labels = [0, 0, 1, 0, 1, 0, 1, 1]
        query = np.array([-100, 0, 0.25, 0.5, 0.75, 1, 100])
        for method in ("raw", "sigmoid", "isotonic"):
            with self.subTest(method=method):
                fitted = ProbabilityCalibration.fit(method, probabilities, labels)
                restored = ProbabilityCalibration(**json.loads(json.dumps(asdict(fitted), allow_nan=False)))
                result = fitted.transform(query)
                np.testing.assert_array_equal(result, restored.transform(query))
                self.assertTrue(np.isfinite(result).all())
                self.assertTrue(((result > 0) & (result < 1)).all())
                self.assertEqual(fitted.transform([]).shape, (0,))

    def test_single_class_calibration_fails_explicitly(self):
        for method in ("sigmoid", "isotonic"):
            with self.assertRaisesRegex(ValueError, "both cancellation outcomes"):
                ProbabilityCalibration.fit(method, [0.1, 0.2], [0, 0])

    def test_metrics_handle_empty_and_single_class_slices(self):
        self.assertEqual(probability_metrics([], [])["rows"], 0)
        self.assertIsNone(probability_metrics([], [])["log_loss"])
        metrics = probability_metrics([0, 0], [0.1, 0.2])
        self.assertIsNone(metrics["auc"])
        self.assertAlmostEqual(metrics["brier"], 0.025)


if __name__ == "__main__":
    unittest.main()
