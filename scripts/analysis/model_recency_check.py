"""Does the model get better if recent bookings count more, or if it also trains on the calibration months?

Same S2 set-up as calibration_check.py (train Jul 2015-Mar 2016, calibrate
Apr-Jun 2016, score Jul-Sep 2016 requests; October-December is not touched).

  recency   training rows are weighted 0.5 ** (age / half-life)
  extended  a second model is trained on train + calibration months with the same
            recipe; the calibrator still comes from the first model's predictions
            on the calibration months, which that model never saw

uv run python scripts/analysis/model_recency_check.py
"""

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier

import calibration_check as c  # loads the data and builds the S2 feature tables
from hackathon.cancellation import ProbabilityCalibration, probability_metrics
from hackathon.preprocessing import MODEL_CATEGORICAL, MODEL_FEATURES

COLUMNS, CATS = list(MODEL_FEATURES), list(MODEL_CATEGORICAL)
newest = c.cal.arrival_date.max()


def weights(frame: pd.DataFrame, half_life):
    if half_life is None:
        return None
    age = (newest - pd.to_datetime(frame.arrival_date)).dt.days.to_numpy()
    return 0.5 ** (age / half_life)


def fit(x, y, weight=None):
    model = CatBoostClassifier(iterations=337, depth=6, learning_rate=0.05, random_seed=2026, thread_count=4,
                               cat_features=CATS, verbose=False, allow_writing_files=False)
    return model.fit(x[COLUMNS], y, sample_weight=weight)


def report(name, raw_cal, raw_tune):
    for method in ("sigmoid", "isotonic"):
        p = ProbabilityCalibration.fit(method, raw_cal, c.y_cal).transform(raw_tune)
        r = probability_metrics(c.y_tune[c.is_request], p[c.is_request])
        a = probability_metrics(c.y_tune, p)
        print(f"{name:34s} {method:9s} requests: pred={r['mean_p_cancel']:.3f} obs={r['cancel_rate']:.3f} "
              f"ll={r['log_loss']:.4f} auc={r['auc']:.3f} | all: pred={a['mean_p_cancel']:.3f} "
              f"obs={a['cancel_rate']:.3f} ll={a['log_loss']:.4f} auc={a['auc']:.3f}", flush=True)


both_x = pd.concat([c.x_train, c.x_cal])
both_y = np.r_[c.y_train, c.y_cal]
both_rows = pd.concat([c.train, c.cal])
for half_life in (None, 365, 180, 90):
    label = "no weighting" if half_life is None else f"half-life {half_life} days"
    first = fit(c.x_train, c.y_train, weights(c.train, half_life))
    raw_cal = first.predict_proba(c.x_cal[COLUMNS])[:, 1]
    report(f"current split, {label}", raw_cal, first.predict_proba(c.x_tune[COLUMNS])[:, 1])
    second = fit(both_x, both_y, weights(both_rows, half_life))
    report(f"extended,      {label}", raw_cal, second.predict_proba(c.x_tune[COLUMNS])[:, 1])
