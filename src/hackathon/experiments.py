"""Shared set-up for policy replays on permitted history (tuning and confirmation)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
from time import perf_counter

import numpy as np
import pandas as pd

from hackathon.cancellation import CancellationModel
from hackathon.contracts import policy_inputs
from hackathon.policy import DemandHistory, PolicyParams, policy_factory
from hackathon.simulator import ScoringRules, prepare_replay, replay_prepared, slice_result
from hackathon.splits import Period, replay_population


def _validated_p_show(frame: pd.DataFrame, expected_ids) -> dict:
    """Require exactly one finite probability for every booking in the stream."""
    if not {"booking_id", "p_show"}.issubset(frame.columns):
        raise ValueError("Prediction cache needs booking_id and p_show columns")
    ids = pd.Index(frame.booking_id)
    expected = pd.Index(expected_ids)
    if (ids.hasnans or ids.has_duplicates or expected.hasnans or expected.has_duplicates
            or len(ids) != len(expected) or len(ids.difference(expected))):
        raise ValueError("Prediction cache booking IDs do not match the replay population")
    probability = pd.to_numeric(frame.p_show, errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(probability).all() or ((probability < 0) | (probability > 1)).any():
        raise ValueError("Prediction cache probabilities must be finite and between zero and one")
    return dict(zip(ids, probability))


def cached_p_show(data: pd.DataFrame, model_directory: str | Path, period: Period) -> dict:
    """Cache predictions by model and outcome-free inputs; preserve legacy caches."""
    directory = Path(model_directory)
    commitments, requests = replay_population(data, period)
    population = policy_inputs(pd.concat([commitments, requests]))
    fingerprint = hashlib.sha256((directory / "model.json").read_bytes())
    fingerprint.update(json.dumps({"version": 1, "start": period.start, "end": period.end,
                                   "columns": list(population.columns),
                                   "dtypes": list(map(str, population.dtypes))}, sort_keys=True).encode())
    fingerprint.update(pd.util.hash_pandas_object(population, index=False).values.tobytes())
    path = directory / f"p_show_{period.start}_{period.end}_{fingerprint.hexdigest()}.csv"
    if path.exists():
        return _validated_p_show(pd.read_csv(path), population.booking_id)
    model = CancellationModel.load(directory)
    frame = pd.DataFrame({"booking_id": population.booking_id.to_numpy(),
                          "p_show": 1 - model.p_cancel(population)})
    probabilities = _validated_p_show(frame, population.booking_id)
    # Several tuning workers may build the same cache. Publish only a complete
    # CSV so another worker cannot read a partially written file.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=directory,
                                         suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            frame.to_csv(handle, index=False)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return probabilities


class Bench:
    """One replay stream scored under both readings of 'cheapest'."""

    def __init__(self, data, start, end, demand_cutoff, p_show, report=None):
        self.p_show, self.report = p_show, report
        self.demand = DemandHistory.from_rows(data, demand_cutoff)
        self.prepared = {reading: prepare_replay(data, start, end, rules=ScoringRules(cheapest=reading))
                         for reading in ("stay_value", "nightly_rate")}

    def run(self, params: PolicyParams | None = None, reading: str = "stay_value", factory=None, record=False):
        params = params or PolicyParams()
        holder: list = []
        if factory is None:
            params = PolicyParams.from_dict({**params.__dict__, "cheapest": reading})
            factory = policy_factory(demand=self.demand, p_show=self.p_show, params=params,
                                     record=record, holder=holder)
        started = perf_counter()
        result = replay_prepared(self.prepared[reading], factory)
        if self.report:
            result = slice_result(result, *self.report)
        result.summary["seconds"] = perf_counter() - started
        result.policy = holder[0] if holder else None
        return result


STREAMS = {
    "s2": "Jul-Sep 2016 arrivals, replay from 1 Jul 2016 (commitment-heavy tuning period)",
    "year": "Jan-Sep 2016 arrivals, replay from 1 Jan 2016 with rolling probabilities (2017 look-alike)",
    "confirm": "Oct-Dec 2016 arrivals, replay from 1 Jul 2016 (previously inspected; development result)",
}


def build_stream(stream: str, data_path: str = "data/train.csv", *,
                 model_directory: str | Path = "artifacts/cancellation_s2",
                 rolling_path: str | Path = "artifacts/rolling_2016/p_show.csv") -> Bench:
    """Historical replay streams, including the former confirmation period."""
    from hackathon.contracts import load_history

    data = load_history(data_path)
    if stream in ("s2", "confirm"):
        p_show = cached_p_show(data, model_directory, Period("2016-07-01", "2017-01-01"))
        if stream == "s2":
            return Bench(data, "2016-07-01", "2016-09-30", "2016-07-01", p_show)
        # Policy state must run on from July; only October onward is reported.
        return Bench(data, "2016-07-01", "2016-12-31", "2016-07-01", p_show, report=("2016-10-01", "2016-12-31"))
    if stream == "year":
        frame = pd.read_csv(rolling_path)
        population = Period("2016-01-01", "2017-01-01").select(data)
        p_show = _validated_p_show(frame, population.booking_id)
        return Bench(data, "2016-01-01", "2016-12-31", "2016-01-01", p_show,
                     report=("2016-01-01", "2016-09-30"))
    raise ValueError(f"Unknown stream {stream!r}; choose from {list(STREAMS)}")


def line(name: str, result) -> str:
    s = result.summary
    return (f"{name:44s} net={s['net_revenue']:>12,.0f} rev={s['revenue']:>12,.0f} pen={s['penalties']:>11,.0f} "
            f"walks={s['walks']:>5,} accept={s['accept_rate']:6.1%} occ={s['average_occupancy']:5.1%} {s['seconds']:5.1f}s")
