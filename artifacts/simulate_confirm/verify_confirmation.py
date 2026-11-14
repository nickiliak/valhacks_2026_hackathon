"""Check saved confirmation results without rerunning or tuning the policy."""
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
manifest = json.loads((OUT / "run_manifest.json").read_text(encoding="utf-8"))
for name, expected in manifest["sha256"].items():
    assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, name
frozen = json.loads((OUT / "frozen_config.json").read_text(encoding="utf-8"))
assert frozen == json.loads((ROOT / "config/policy.json").read_text(encoding="utf-8"))
assert frozen["policy"] == json.loads((OUT / "settings.json").read_text(encoding="utf-8"))
assert frozen["policy"] == json.loads((ROOT / "artifacts/final/policy.json").read_text(encoding="utf-8"))["params"]

history = pd.read_csv(ROOT / "data/train.csv", parse_dates=["arrival_date", "booking_date"])
assert history.arrival_date.max() < pd.Timestamp("2017-01-01")
source = history.loc[history.arrival_date.between("2016-10-01", "2016-12-31")].set_index("booking_id").sort_index()
summary = pd.read_csv(OUT / "summary.csv")
assert len(summary) == 12
assert summary.start.eq("2016-10-01").all() and summary.end.eq("2016-12-31").all()
assert summary.replay_start.eq("2016-07-01").all()
np.testing.assert_allclose(summary.net_revenue, summary.revenue - summary.penalties, rtol=0, atol=1e-7)
reports = []
for reading in ("stay_value", "nightly_rate"):
    log = pd.read_csv(OUT / f"{reading}_decisions.csv", parse_dates=["arrival_date", "booking_date"])
    assert not log.booking_id.duplicated().any()
    actual = log.set_index("booking_id").sort_index()
    columns = ["hotel", "cancelled", "nights", "nightly_rate", "arrival_date", "booking_date"]
    pd.testing.assert_frame_equal(actual[columns], source[columns], check_dtype=False)
    assert (log.committed == log.booking_date.lt("2016-07-01")).all()
    assert log.loc[log.committed, "accepted"].all()
    assert log.loc[~log.committed, "reason"].notna().all(), "Missing decision reasons may indicate fallback"
    assert log.status.isin(["rejected", "cancelled", "walked", "seated"]).all()
    assert (log.status.eq("rejected") == ~log.accepted).all()
    assert (log.status.eq("cancelled") == (log.accepted & log.cancelled.eq(1))).all()
    value = log.nightly_rate * log.nights
    revenue = np.where(log.status.eq("seated"), value, 0.0)
    penalties = np.where(log.status.eq("walked"), 2.5 * value, 0.0)
    for column, expected in (("revenue", revenue), ("penalties", penalties), ("net_revenue", revenue - penalties)):
        np.testing.assert_allclose(log[column], expected, rtol=0, atol=1e-8)
    daily = pd.read_csv(OUT / f"{reading}_occupancy.csv", parse_dates=["date"])
    assert len(daily) == 184 and not daily.duplicated(["hotel", "date"]).any()
    assert daily.date.between("2016-10-01", "2016-12-31").all()
    assert daily.rooms.eq(daily.hotel.map({"Downtown Hotel": 124, "Seaside Hotel": 103})).all()
    assert ((daily.occupied >= 0) & (daily.occupied <= daily.rooms)).all()
    metrics = {
        "revenue": float(revenue.sum()), "penalties": float(penalties.sum()),
        "net_revenue": float((revenue - penalties).sum()),
        "walks": int(log.status.eq("walked").sum()), "seated": int(log.status.eq("seated").sum()),
        "commitments": int(log.committed.sum()), "requests": int((~log.committed).sum()),
        "accepted_requests": int((log.accepted & ~log.committed).sum()),
        "occupied_room_nights": int(daily.occupied.sum()), "available_room_nights": int(daily.rooms.sum()),
    }
    runs = summary.loc[summary.reading.eq(reading)].set_index("policy")
    ours = runs.loc["OUR POLICY"]
    for key, expected in metrics.items():
        np.testing.assert_allclose(ours[key], expected, rtol=0, atol=1e-7)
    for suffix in ("hotels", "months"):
        totals = pd.read_csv(OUT / f"{reading}_{suffix}.csv")[list(metrics)].sum()
        for key, expected in metrics.items():
            np.testing.assert_allclose(totals[key], expected, rtol=0, atol=1e-7)
    baseline = runs.loc["average-rate overbooking"]
    reports.append({"reading": reading, "all_checks_passed": True, "bookings_verified": len(log),
                    **metrics, "net_uplift_vs_average_rate": float(ours.net_revenue - baseline.net_revenue),
                    "net_uplift_percent": float(100 * (ours.net_revenue / baseline.net_revenue - 1)),
                    "walk_reduction_percent": float(100 * (1 - ours.walks / baseline.walks))})

result = {"all_checks_passed": True, "frozen_inputs_unchanged": True, "final_bundle_unchanged": True,
          "method": "Saved source rows, financial accounting, decision completeness, occupancy bounds, and aggregate reconciliation; no policy rerun",
          "limitations": "Reconstructed scorer; no independent reseating audit of July-September carryover. Nightly-rate sensitivity changes both scorer and policy walk ordering.",
          "reports": reports}
(OUT / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result, indent=2))
