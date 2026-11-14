"""Validate probability calibration on S2 without touching October-December.

Train: Jul 2015-Mar 2016. Calibrate: Apr-Jun 2016. Score: Jul-Sep 2016 requests.
Compares feature subsets, regularisation, and calibrators (raw, sigmoid,
sigmoid with lead time). Prints mean predicted vs observed cancellation.

uv run python scripts/analysis/calibration_check.py
"""

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.linear_model import LogisticRegression

from hackathon.cancellation import probability_metrics
from hackathon.contracts import load_history
from hackathon.preprocessing import CATEGORICAL_FEATURES, FEATURE_COLUMNS, FeatureBuilder
from hackathon.splits import get_split, replay_population

rows = load_history("data/train.csv")
split = get_split("S2")
train, cal = split.train.select(rows), split.calibration.select(rows)
commitments, requests = replay_population(rows, split.tuning)
population = pd.concat([commitments, requests])
is_request = np.r_[np.zeros(len(commitments), bool), np.ones(len(requests), bool)]
builder = FeatureBuilder().fit(train)
x_train, x_cal, x_tune = (builder.make_features(f) for f in (train, cal, population))
y_train, y_cal, y_tune = (f.cancelled.to_numpy(int) for f in (train, cal, population))


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def design(p, x, with_lead):
    columns = [logit(p)]
    if with_lead:
        columns += [np.log1p(x.days_ahead.to_numpy()), (x.hotel == "Seaside Hotel").to_numpy(float)]
    return np.column_stack(columns)


def run(name, drop=(), per_hotel=True, **params):
    columns = [c for c in FEATURE_COLUMNS if c not in drop]
    cats = [c for c in CATEGORICAL_FEATURES if c not in drop]
    settings = dict(iterations=250, depth=6, learning_rate=0.05, random_seed=2026, thread_count=4,
                    cat_features=cats, verbose=False, allow_writing_files=False)
    settings.update(params)
    raw_cal, raw_tune = np.empty(len(x_cal)), np.empty(len(x_tune))
    for hotel in (sorted(x_train.hotel.unique()) if per_hotel else [None]):
        pick = lambda x: np.ones(len(x), bool) if hotel is None else (x.hotel == hotel).to_numpy()
        model = CatBoostClassifier(**settings).fit(x_train.loc[pick(x_train), columns], y_train[pick(x_train)])
        raw_cal[pick(x_cal)] = model.predict_proba(x_cal.loc[pick(x_cal), columns])[:, 1]
        raw_tune[pick(x_tune)] = model.predict_proba(x_tune.loc[pick(x_tune), columns])[:, 1]
    outputs = {"raw": raw_tune}
    for label, with_lead in (("sigmoid", False), ("sigmoid+lead", True)):
        fit = LogisticRegression(C=1e6, max_iter=2000).fit(design(raw_cal, x_cal, with_lead), y_cal)
        outputs[label] = fit.predict_proba(design(raw_tune, x_tune, with_lead))[:, 1]
    for label, p in outputs.items():
        r, a = probability_metrics(y_tune[is_request], p[is_request]), probability_metrics(y_tune, p)
        print(f"{name:26s} {label:13s} requests: pred={r['mean_p_cancel']:.3f} obs={r['cancel_rate']:.3f} "
              f"ll={r['log_loss']:.4f} auc={r['auc']:.3f} | all: pred={a['mean_p_cancel']:.3f} "
              f"obs={a['cancel_rate']:.3f} ll={a['log_loss']:.4f} auc={a['auc']:.3f}", flush=True)


SEASON = ("arrival_month", "booking_month", "arrival_week")
if __name__ == "__main__":
    import sys
    if "--round1" in sys.argv:
        run("baseline per-hotel")
        run("no agent/company", drop=("agent", "company"))
        run("no agent/company/country", drop=("agent", "company", "country"))
        run("no seasonal categories", drop=SEASON)
        run("combined shallow", per_hotel=False, depth=4, learning_rate=0.03, iterations=300, l2_leaf_reg=10)
        run("per-hotel shallow", depth=4, learning_rate=0.03, iterations=300, l2_leaf_reg=10)
    else:
        run("no season", drop=SEASON)
        run("no season, combined", drop=SEASON, per_hotel=False)
        run("no season/weekday", drop=SEASON + ("arrival_weekday", "booking_weekday"))
        run("no season/rate_vs_typical", drop=SEASON + ("rate_vs_typical",))
        run("no season/company", drop=SEASON + ("company",))
        run("no season, 500 trees", drop=SEASON, iterations=500)
        run("no season, 120 trees", drop=SEASON, iterations=120)
