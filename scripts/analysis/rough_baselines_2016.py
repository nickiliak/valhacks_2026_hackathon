import sys
import numpy as np
import pandas as pd

df = pd.read_csv(sys.argv[1], parse_dates=["arrival_date", "booking_date"])
df["stay_value"] = df.nightly_rate * df.nights
ROOMS = {"Downtown Hotel": 124, "Seaside Hotel": 103}

# NOTE: the `deposit` column was dropped from train.csv on 14 Nov; nothing below uses it.
y16 = df[df.arrival_date.dt.year == 2016]

# (b) base-rate drift, same half-year
for h in ROOMS:
    for yr in (2015, 2016):
        g = df[(df.hotel == h) & (df.arrival_date.dt.year == yr) & (df.arrival_date.dt.month >= 7)]
        print(f"{h} H2-{yr}: cancel {g.cancelled.mean():.3f}  n={len(g)}")

# (c) rough replay of 2016: accept-all vs FCFS(cap on bookings) vs cap on expected shows
# rule: walk at arrival night only; cheapest = lowest stay value; seated keep room; no 2015 in-house (approx)
def replay(g, accept_mask, rooms):
    g = g[accept_mask & (g.cancelled == 0)].sort_values("arrival_date")
    inhouse = np.zeros(400)  # day index offset from 2016-01-01
    base = pd.Timestamp("2016-01-01")
    rev = pen = walks = 0.0
    for d, arr in g.groupby("arrival_date"):
        i = (d - base).days
        free = rooms - inhouse[i]
        arr = arr.sort_values("stay_value", ascending=False)
        seated = arr.iloc[: max(int(free), 0)]
        walked = arr.iloc[max(int(free), 0):]
        rev += seated.stay_value.sum()
        pen += 2.5 * walked.stay_value.sum()
        walks += len(walked)
        for n in seated.nights.values:
            inhouse[i : i + n] += 1
    return rev, pen, walks

for h, rooms in ROOMS.items():
    g = y16[y16.hotel == h].sort_values(["booking_date", "booking_id"]).reset_index(drop=True)
    base = pd.Timestamp("2016-01-01")
    # accept-all
    r, p, w = replay(g, np.ones(len(g), bool), rooms)
    print(f"\n{h} ACCEPT-ALL: revenue {r:,.0f}  penalty {p:,.0f}  net {r-p:,.0f}  walks {w:.0f}")
    # FCFS on bookings: accept while booked count on every night of stay < rooms
    for label, weight in (("FCFS bookings<=rooms", None), ("cap expected shows (avg p)", "p")):
        booked = np.zeros(400)
        acc = np.zeros(len(g), bool)
        pbar = 1 - g.cancelled.mean()
        for k, row in enumerate(g.itertuples(index=False)):
            i = (row.arrival_date - base).days
            w_ = 1.0 if weight is None else pbar
            if (booked[i : i + row.nights] + w_).max() <= rooms:
                acc[k] = True
                booked[i : i + row.nights] += w_
        r, p, w = replay(g, acc, rooms)
        print(f"{h} {label}: accepted {acc.mean():.1%}  revenue {r:,.0f}  penalty {p:,.0f}  net {r-p:,.0f}  walks {w:.0f}")
    # hindsight-ish greedy: accept only shows, highest value first, if room on all nights
    s = g[g.cancelled == 0].sort_values("stay_value", ascending=False)
    booked = np.zeros(400); acc = pd.Series(False, index=g.index)
    for idx, row in s.iterrows():
        i = (row.arrival_date - base).days
        if (booked[i : i + row.nights] + 1).max() <= rooms:
            acc[idx] = True; booked[i : i + row.nights] += 1
    r, p, w = replay(g, acc.values, rooms)
    print(f"{h} GREEDY HINDSIGHT (lower bound on ceiling): net {r-p:,.0f}")
