"""Where did we leave money? Rejected guests who showed up vs rooms that stayed empty.

Reads a finished simulate.py run. For every hotel night it takes the rooms left
empty at the end, then asks with hindsight: which rejected requests actually
showed up and would have fitted into rooms that stayed empty on every night of
their stay? Those are filled greedily, most valuable first, and the revenue is
attributed to the rule that rejected them.

This is an upper bound on what a better rule could recover: it knows who showed,
and it ignores the extra walk risk of holding more bookings.

uv run python scripts/analysis/empty_rooms.py artifacts/simulate_year
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

folder = Path(sys.argv[1] if len(sys.argv) > 1 else "artifacts/simulate_year")
reading = sys.argv[2] if len(sys.argv) > 2 else "stay_value"
log = pd.read_csv(folder / f"{reading}_decisions.csv", parse_dates=["arrival_date", "booking_date"])
nights = pd.read_csv(folder / f"{reading}_occupancy.csv", parse_dates=["date"])
log["reason"] = log.reason.fillna("commitment").str.replace(r"rate \d+ below minimum price \d+", "rate below minimum price", regex=True)
log["stay_value"] = log.nightly_rate * log.nights
log["month"] = log.arrival_date.dt.strftime("%m")
log["lead"] = pd.cut(log.days_ahead, [-1, 7, 30, 90, 180, 9999], labels=["0-7", "8-30", "31-90", "91-180", "181+"])
day0, last = nights.date.min(), nights.date.max()
print(f"{folder} ({reading}): arrivals {day0.date()} to {last.date()}")

free = {}
for hotel, part in nights.groupby("hotel"):
    part = part.sort_values("date")
    free[hotel] = (part.rooms - part.occupied).to_numpy().astype(int)
empty_before = {h: f.copy() for h, f in free.items()}

rejected = log.loc[~log.committed & ~log.accepted].copy()
showed = rejected.loc[rejected.cancelled.eq(0)].sort_values("stay_value", ascending=False)
recovered = []
for row in showed.itertuples():
    start = (row.arrival_date - day0).days
    stop = min(start + row.nights, len(free[row.hotel]))
    if (free[row.hotel][start:stop] > 0).all():
        free[row.hotel][start:stop] -= 1
        recovered.append(row.Index)
rejected["recoverable"] = rejected.index.isin(recovered)

print("\n1. Rooms that stayed empty")
for hotel in free:
    total = len(free[hotel]) * nights.loc[nights.hotel.eq(hotel), "rooms"].iloc[0]
    print(f"   {hotel}: {empty_before[hotel].sum():,} empty room-nights of {total:,} ({empty_before[hotel].sum() / total:.0%}); "
          f"{empty_before[hotel].sum() - free[hotel].sum():,} of them could have held a rejected guest who showed up")

print("\n2. Rejected requests by rule (all hotels)")
table = rejected.groupby("reason").agg(
    rejected=("booking_id", "size"), showed_up=("cancelled", lambda c: int((c == 0).sum())),
    avg_rate=("nightly_rate", "mean"), fit_in_empty_rooms=("recoverable", "sum"),
    revenue_left=("stay_value", lambda v: v[rejected.loc[v.index, "recoverable"]].sum()))
print(table.sort_values("revenue_left", ascending=False).round(0).to_string())
accepted = log.loc[~log.committed & log.accepted]
earned = log.revenue.sum() - log.penalties.sum()
print(f"   accepted requests: {len(accepted):,}, average rate {accepted.nightly_rate.mean():.0f}; net revenue earned {earned:,.0f}; "
      f"revenue left in empty rooms {rejected.loc[rejected.recoverable, 'stay_value'].sum():,.0f}")

left = rejected.loc[rejected.recoverable]
for by in (["hotel", "reason"], ["hotel", "month"], ["reason", "lead"]):
    print(f"\n3. Revenue left in empty rooms by {' and '.join(by)} (EUR thousand)")
    print((left.groupby(by, observed=True).stay_value.sum() / 1000).round(0).unstack(fill_value=0).to_string())

price = left.loc[left.reason.eq("rate below minimum price")]
if len(price):
    ratio = price.nightly_rate / price.min_price
    print("\n4. Price rejections that would have fitted: how far below the minimum price was the rate?")
    print("   " + ", ".join(f"{label}: {int(((ratio > low) & (ratio <= high)).sum()):,}"
                             for label, low, high in [("under 50%", 0, .5), ("50-75%", .5, .75), ("75-90%", .75, .9), ("90-100%", .9, 1)]))
    print(f"   their average rate {price.nightly_rate.mean():.0f} vs average minimum price asked {price.min_price.mean():.0f}")
risk = left.loc[left.reason.str.startswith("expected walk cost")]
if len(risk):
    share = -risk.delta / (risk.p_show * risk.stay_value)
    print("\n5. Walk-cost rejections that would have fitted: simulated loss as a share of the booking's expected revenue")
    print("   " + ", ".join(f"{label}: {int(((share > low) & (share <= high)).sum()):,}"
                             for label, low, high in [("0-10%", -1, .1), ("10-50%", .1, .5), ("50-100%", .5, 1), ("over 100%", 1, 1e9)]))
    print(f"   their predicted show-up {risk.p_show.mean():.0%}; they all showed. All walk-cost rejections: predicted "
          f"{rejected.loc[rejected.reason.str.startswith('expected walk cost'), 'p_show'].mean():.0%}, actual "
          f"{1 - rejected.loc[rejected.reason.str.startswith('expected walk cost'), 'cancelled'].mean():.0%}")
