"""Replay caches must follow the model and permitted input population."""

import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

from hackathon.experiments import build_stream, cached_p_show
from hackathon.splits import Period


def bookings():
    return pd.DataFrame({
        "booking_id": [1, 2, 3], "hotel": ["Downtown Hotel"] * 3,
        "booking_date": pd.to_datetime(["2016-06-01", "2016-07-01", "2016-08-01"]),
        "arrival_date": pd.to_datetime(["2016-07-05", "2016-08-05", "2016-10-05"]),
        "nightly_rate": [90.0, 110.0, 120.0], "cancelled": [0, 1, 0],
    })


class PredictionCacheTests(unittest.TestCase):
    period = Period("2016-07-01", "2017-01-01")

    def test_cache_reuses_only_the_same_model_and_permitted_inputs(self):
        rows = bookings()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            metadata = directory / "model.json"
            metadata.write_text(json.dumps({"cancel_probability": 0.2}))
            legacy = directory / "p_show_2016-07-01_2017-01-01.csv"
            legacy.write_text("legacy cache must remain unchanged")
            seen = []

            def load(path):
                probability = json.loads((path / "model.json").read_text())["cancel_probability"]

                def predict(population):
                    seen.append(population.copy())
                    return np.full(len(population), probability)

                return SimpleNamespace(p_cancel=predict)

            with patch("hackathon.experiments.CancellationModel.load", side_effect=load) as loader:
                first = cached_p_show(rows, directory, self.period)
                self.assertEqual(first, cached_p_show(rows, directory, self.period))
                relabelled = rows.copy()
                relabelled["cancelled"] = 1 - relabelled.cancelled
                relabelled["deposit"] = "unavailable"
                self.assertEqual(first, cached_p_show(relabelled, directory, self.period))
                self.assertEqual(loader.call_count, 1)
                metadata.write_text(json.dumps({"cancel_probability": 0.4}))
                changed_model = cached_p_show(rows, directory, self.period)
                self.assertNotEqual(first, changed_model)
                changed_input = rows.copy()
                changed_input.loc[0, "nightly_rate"] += 10
                cached_p_show(changed_input, directory, self.period)
                self.assertEqual(loader.call_count, 3)
                self.assertEqual(len(list(directory.glob("p_show_*_*.csv"))), 4)
            self.assertEqual(legacy.read_text(), "legacy cache must remain unchanged")
            self.assertTrue(all(not {"cancelled", "deposit"}.intersection(frame.columns) for frame in seen))
            self.assertFalse(list(directory.glob("*.tmp")))

    def test_cache_rejects_wrong_ids_and_invalid_probabilities(self):
        rows = bookings()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "model.json").write_text("{}")
            model = SimpleNamespace(p_cancel=Mock(return_value=np.full(3, 0.2)))
            with patch("hackathon.experiments.CancellationModel.load", return_value=model):
                cached_p_show(rows, directory, self.period)
                path = next(directory.glob("p_show_*.csv"))
                valid = pd.read_csv(path)
                variants = [
                    valid.assign(booking_id=[1, 1, 3]),
                    valid.assign(booking_id=[1, 2, 99]),
                    valid.assign(p_show=[0.2, np.nan, 0.3]),
                    valid.assign(p_show=[0.2, 1.1, 0.3]),
                ]
                for frame in variants:
                    frame.to_csv(path, index=False)
                    with self.assertRaisesRegex(ValueError, "Prediction cache"):
                        cached_p_show(rows, directory, self.period)
                self.assertEqual(model.p_cancel.call_count, 1)

    def test_invalid_model_probability_is_not_cached(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "model.json").write_text("{}")
            model = SimpleNamespace(p_cancel=Mock(return_value=np.array([0.2, np.nan, 0.4])))
            with patch("hackathon.experiments.CancellationModel.load", return_value=model):
                with self.assertRaisesRegex(ValueError, "finite"):
                    cached_p_show(bookings(), directory, self.period)
            self.assertFalse(list(directory.glob("p_show_*.csv")))


class ReplayRoutingTests(unittest.TestCase):
    def test_stream_uses_explicit_model_and_rolling_paths(self):
        rows = bookings()
        probabilities = dict(zip(rows.booking_id, [0.2, 0.3, 0.4]))
        with patch("hackathon.contracts.load_history", return_value=rows), \
                patch("hackathon.experiments.Bench") as bench, \
                patch("hackathon.experiments.cached_p_show", return_value=probabilities) as cached:
            build_stream("s2", "custom.csv", model_directory="custom-model")
            self.assertEqual(cached.call_args.args[1], "custom-model")
            self.assertEqual(bench.call_args.args[4], probabilities)
            build_stream("confirm")
            self.assertEqual(cached.call_args.args[1], "artifacts/cancellation_s2")
            self.assertEqual(bench.call_args.kwargs["report"], ("2016-10-01", "2016-12-31"))
            frame = pd.DataFrame({"booking_id": rows.booking_id, "p_show": list(probabilities.values())})
            with patch("hackathon.experiments.pd.read_csv", return_value=frame) as reader:
                build_stream("year", rolling_path="custom-rolling.csv")
                self.assertEqual(reader.call_args.args[0], "custom-rolling.csv")
                self.assertEqual(bench.call_args.args[4], probabilities)

    def test_tuning_overrides_keep_configured_policy_and_replay_paths(self):
        path = Path(__file__).resolve().parents[1] / "scripts" / "tune_policy.py"
        spec = importlib.util.spec_from_file_location("_tune_policy_test", path)
        tune = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tune)
        result = SimpleNamespace(
            by_hotel=pd.DataFrame({"hotel": ["Downtown Hotel"], "net_revenue": [100.0]}),
            summary={"net_revenue": 100.0, "revenue": 100.0, "penalties": 0.0, "walks": 0,
                     "accept_rate": 0.5, "average_occupancy": 0.8, "seconds": 0.01},
        )
        bench = SimpleNamespace(run=Mock(return_value=result))
        with patch.object(tune, "build_stream", return_value=bench) as build:
            tune.start("s2", "custom.csv", {"load_target": 0.9, "raw_cap": 3.0, "price_mult": 1.2},
                       {"s2_model": "context-model", "rolling_probabilities": "context-rolling.csv"})
        self.assertEqual(build.call_args.kwargs, {"model_directory": "context-model",
                                                  "rolling_path": "context-rolling.csv"})
        row = tune.run(({"price_mult": 0.75}, "stay_value"))
        params = bench.run.call_args.args[0]
        self.assertEqual((params.load_target, params.raw_cap, params.price_mult), (0.9, 3.0, 0.75))
        self.assertEqual((row["load_target"], row["raw_cap"], row["price_mult"]), (0.9, 3.0, 0.75))


if __name__ == "__main__":
    unittest.main()
