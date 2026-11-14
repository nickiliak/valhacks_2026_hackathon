"""Shared set-up for policy replays on permitted history (tuning and confirmation)."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter

import pandas as pd

from hackathon.cancellation import CancellationModel
from hackathon.contracts import policy_inputs
from hackathon.policy import DemandHistory, PolicyParams, policy_factory
from hackathon.simulator import ScoringRules, prepare_replay, replay_prepared, slice_result
from hackathon.splits import Period, replay_population


def cached_p_show(data: pd.DataFrame, model_directory: str | Path, period: Period) -> dict:
    """Show-up probability per booking_id for one replay stream (no outcomes used)."""
    path = Path(model_directory) / f"p_show_{period.start}_{period.end}.csv"
    if path.exists():
        frame = pd.read_csv(path)
    else:
        model = CancellationModel.load(model_directory)
        commitments, requests = replay_population(data, period)
        population = policy_inputs(pd.concat([commitments, requests]))
        frame = pd.DataFrame({"booking_id": population.booking_id.to_numpy(),
                              "p_show": 1 - model.p_cancel(population)})
        frame.to_csv(path, index=False)
    return dict(zip(frame.booking_id, frame.p_show))


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


def line(name: str, result) -> str:
    s = result.summary
    return (f"{name:44s} net={s['net_revenue']:>12,.0f} rev={s['revenue']:>12,.0f} pen={s['penalties']:>11,.0f} "
            f"walks={s['walks']:>5,} accept={s['accept_rate']:6.1%} occ={s['average_occupancy']:5.1%} {s['seconds']:5.1f}s")
