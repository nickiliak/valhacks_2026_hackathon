# 06: Layer 1, the show-up model

## Purpose
For every booking, `p_show` = probability the guest arrives. Used for **accounting** (expected rooms per night) and **risk** (chance of overflow). Not used to filter out likely cancellers (Insight 2).

```
features (04) → CatBoost predicts p_cancel → calibrate → p_show = 1 − p_cancel
```
`cancelled` covers both cancellations and no-shows, so `1 − p_cancel` is the show-up probability.

## Model choice
| Model | Role | Note |
|---|---|---|
| **CatBoost** | Main | Native categorical handling (country, agent, company, segment) with ordered target statistics, which avoids a classic leakage trap. **Not installed yet:** `uv add catboost`. CPU is fine: 78k rows train in seconds; GPU gives nothing here |
| LightGBM | Second opinion | Already installed. Only blend if it clearly helps on S2 |
| Logistic regression | Baseline + pitch | "Each factor adds or subtracts points." Needs NaN filling and one-hot; keep it simple |

Train per hotel or with `hotel` as a feature; try both, pick by log loss on the **internal validation slice** (last ~2 months of the training period, held out from fitting).

## Settings
- Loss: log loss (binary). Early stopping on the **internal validation slice**, never on the calibration or confirm periods. The calibration period is used only to fit the calibrator.
- **No SMOTE, no oversampling, no class weights**: they distort probabilities.
- Modest depth (6–8), learning rate ~0.05, a few hundred to a few thousand trees with early stopping.
- Optional variants (04), only if time allows: without `agent` + `company`; without `amendments` + `special_requests`. No "without country" variant: `country` stays in.
- Expect weaker numbers than published results for this dataset: `deposit` was one of its top-two features and is gone. Log loss on the internal validation slice (model choice) and on the tune period (calibration choice) are the yardsticks, not a target AUC.

## Calibration
- Fit on the calibration period (data the model didn't train on). Try sigmoid/Platt first, isotonic if the period has several thousand rows.
- **Decide raw vs calibrated on tuning data only** (the Jul–Sep 2016 tune period of S2, or a held-out slice of the calibration period), then freeze. The Oct–Dec confirm period is evaluated **once**, at the end, and never used for any choice.
- Early stopping and model selection use an internal validation slice taken from the end of the training period, not the calibration or confirm periods.
- Check a calibration plot per hotel and per lead-time band, and on the decision-like slice (`days_ahead ≤ 365`).
- Expect drift in 2017 (02: cancel rates moved several points between years). Nothing can detect it during the run; the guardrails in 03 cover it.

## Metrics, in priority order
1. **Log loss and Brier score** (probability quality).
2. **Calibration plot** (honesty by band).
3. **AUC** (ranking). Expect roughly 0.85–0.90 out-of-time. Published 0.95+ numbers for this dataset used random splits.
4. **Money in the replay** (09), the metric that counts.

## Groups
Rows of a block are near-duplicates and share outcomes, so the model's rows are not independent. Time splits keep blocks on one side. The *risk* treatment (one flip per block) lives in 07; the model just needs `block_size_so_far` if we build it.

## Output
`p_show(rows) -> array` applied to all commitments at start-up and to each booking in `decide()`. For `decide()`, build the feature vector from the dict directly (no DataFrame per call) or batch; time a full 44k-call replay.

## Explainability hooks
- SHAP summary chart: top drivers of cancellation (lead time, segment, special requests, country, agent, block size, past cancellations).
- SHAP for one booking, converted to plain-language reason codes.
- Plain-language reason codes for the demo.
