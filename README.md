# Valhacks 2026

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1   # installs uv, Python 3.12 and deps into .venv
uv run python scripts/unpack.py                         # extract the kits to data/ (password at kick-off)
```

Add packages with `uv add <pkg>` (commit `pyproject.toml` + `uv.lock`). Skills: `.claude/skills/` (Claude Code), `.agents/skills/` (Codex).

The whole pipeline is implemented: chronological splits, shared preprocessing,
historical replay, a calibrated CatBoost cancellation model, nightly minimum
prices, the acceptance policy, and `scripts/solution.py`, which the organisers'
`evaluate(Solution)` can run. The current bundle uses context calibration and
policy settings selected on the January–September development replays.
The original frozen October–December confirmation is archived below. That
period has since been inspected for improvements and is now development data.
The official 2017 evaluation is still pending.

## Run the pipeline

From the repository root with the permitted, deposit-free `data/train.csv`:

```powershell
uv sync
uv run python -m unittest discover -s tests
uv run python scripts/train_cancel_model.py --split S2 --layout combined --calibration context --output artifacts/cancellation_s2_context
uv run python scripts/rolling_probabilities.py --calibration context --output artifacts/rolling_context_2016/p_show.csv
uv run python scripts/build_final.py                                  # deployment model + price tables -> artifacts/final
uv run python scripts/check_solution.py                               # dress rehearsal of scripts/solution.py
uv run python scripts/simulate.py --stream year                       # our policy vs baselines, with config/policy.json
```

The deployment bundle in `artifacts/final` is tracked. The context replay models,
probability caches and local analyses are ignored; recreate the replay inputs
with the commands above. `scripts/solution.py` loads `artifacts/final`; if that
folder is missing it prints a warning and uses a plain capacity rule instead of
crashing.

| File | Role |
|---|---|
| `config/policy.json` | Policy settings, model layout/calibration, and replay input paths. Simulation and deployment use the same policy settings with models fitted to their respective historical windows. Re-run `build_final.py` after changing model or policy settings |
| `src/hackathon/policy.py` | `AcceptancePolicy` (the decision rule), `DemandHistory` (price tables), `RiskSim` (revenue-difference simulation), `thermometer`, `save_bundle` / `load_bundle` |
| `scripts/solution.py` | The official `Solution` class: loads the bundle and delegates to `AcceptancePolicy` |
| `scripts/simulate.py` | One run of the policy plus all baselines on a replay stream; saves decisions with reasons |
| `scripts/tune_policy.py` | Grid of settings on a stream, in parallel, e.g. `--stream year --set load_target=1.0,1.1 --set margin=0,0.1` |
| `scripts/check_solution.py` | Runs the real `Solution` on a 2017-shaped year: timing, crash and odd-input checks. Prints no revenue |
| `scripts/analysis/calibration_check.py` | Evidence for the calibration choices below |

## How a request is decided

1. **Show-up probability.** `p_show = 1 - p_cancel` from the calibrated model.
   Context calibration adjusts the CatBoost probability using hotel, lead time,
   market segment, guest type and pooled agent categories. It is fitted only on
   the designated calibration window.
2. **Ledger.** Per hotel night, the sum of `p_show` over held bookings = expected rooms used.
3. **Guardrails.** Reject free rooms; reject if held bookings on a night would exceed `raw_cap` x hotel rooms.
4. **Minimum price.** For each night we take the guests who actually stayed on the
   same weekday one year earlier (plus the week before and after) and who booked
   later than today. Sorted by rate, they show what the rooms still free are
   worth: the minimum price is the rate of the first of them who would no longer
   fit. Rates are scaled to this year by comparing the commitments on hand with
   those on hand a year earlier. The request must pay at least the average
   minimum over its nights. On a night that is already full in expectation the
   price test steps aside and step 5 decides alone.
5. **Revenue difference.** 200 random show-up scenarios of the bookings we hold
   (one coin per group block), each replayed through the scoring rules with and
   without the request. Accept if the average net revenue is higher with it.
   This contains the request's own revenue, its chance of being walked, and the
   walks it causes among guests we already hold.

Every decision records a reason (`simulate.py` writes them to `*_decisions.csv`).

## Replay streams

| Stream | What it is | Use |
|---|---|---|
| `year` | All of 2016 from 1 Jan, reported for Jan–Sep arrivals. Each request is scored by a model trained only on arrivals before the quarter it was booked in | The 2017 look-alike: few commitments, long lead times |
| `s2` | Jul–Sep 2016 from 1 Jul | The plan's tuning period. Commitments alone overfill it (reject-all still walks 2,429 guests), so it mostly tests displacement |
| `confirm` | Oct–Dec 2016, policy state carried on from 1 Jul | Original frozen results in `artifacts/simulate_confirm`; subsequent runs are development checks, not independent confirmation |

## Current improvement results (14 November 2026)

Context calibration plus the revised policy improves October–December net
revenue by **€73,101.40 (+5.79%)**, after walk penalties. These are historical
development results under our reconstructed scorer, using cheapest total stay
value, full stay revenue, and a walk penalty of 2.5 times stay value.

| Replay | Original net | Improved net | Improvement | Walks, original → improved |
|---|---:|---:|---:|---:|
| Jan–Sep, rolling models | €4,605,839.80 | €4,947,964.76 | +€342,124.96 | 313 → 752 |
| Jul–Sep, S2 model | €437,717.56 | €462,840.09 | +€25,122.54 | 2,491 → 2,487 |
| Oct–Dec, S2 model | €1,261,492.17 | €1,334,593.57 | +€73,101.40 | 255 → 325 |

The first two replays were used to choose the settings and overlap in dates;
their gains must not be added. October–December had already been inspected
before this improvement work, so it is **not an independent confirmation**.
The official 2017 test has not been run. Values above are rounded independently
to cents; [the aggregate CSV](artifacts/improvement_results/replay_comparison.csv)
preserves the scoring precision.

The change replaces global calibration with regularized logistic calibration
(`C=1`) of the raw model probability using hotel, lead time, hotel/segment,
guest type and pooled hotel/agent categories. Calibration is fitted only within
each model's designated calibration window. The original rolling baseline used
sigmoid calibration; the original S2 and Q4 baseline used isotonic calibration.
Policy settings change from `load_target=1.0`, `price_mult=1.0`, `raw_cap=2.5` to
`1.1`, `0.85`, `4.0`. The 200-scenario revenue check and walk penalty are unchanged.
The implementation also fixes occupancy bookkeeping for unusually long stays;
that bug was not observed in the original Q4 replay and is not the claimed
source of the revenue gain.

Q4 earns €88,326.10 more seated revenue and incurs €15,224.70 more penalties.
Occupied room nights rise from 16,727 to 17,576. Downtown gains €76,879.535;
Seaside loses €3,778.135. This is a revenue/risk tradeoff, not a reduction in
walks. Jan–Sep penalties also rise, from €125,221.60 to €309,549.55.
S2 request log loss improves from 0.477404 to 0.458019 and AUC from 0.774586 to
0.802138, but mean predicted cancellation falls from 24.07% to 20.59% versus
24.32% observed: calibration has not improved in every respect.

S2/Q4 results use trees trained July 2015–March 2016 and calibration fitted
April–June 2016. The shipped Final bundle instead trains through September and
calibrates on October–December, so that bundle cannot be used to validate Q4.
Rolling predictions use only arrivals before each booking quarter, as specified
in `scripts/rolling_probabilities.py`. Model fitting uses no 2017 rows or deposit
feature. Warm-up seating is reconstructed from historical arrivals; actual
historical seating is unavailable.

The saved local hindsight calculation gives €1,632,327.615 for the candidate's
Q4 incoming occupancy, leaving €297,734.05 above the improved policy. This uses
future cancellation outcomes and is not an achievable online forecast. The
candidate changes eight incoming hotel-nights (15 fewer occupied room nights
in total), so its ceiling was recomputed instead of reusing the original
€1,622,861.345 ceiling. The saved solver summary is included for context;
the exploratory optimizer and booking-level analysis remain local and ignored.

Review evidence is committed in [artifacts/improvement_results](artifacts/improvement_results):
aggregate replay results, Q4 hotel/month breakdowns, financial checks, settings,
model/input/source fingerprints and validation details. The local suite passed
78 tests, including 12 ignored hindsight-analysis tests; the 66 tests shipped
with this branch also pass on their own. The real `Solution` rehearsal processed
44,247 requests in 52.0 seconds with zero normal-input fallbacks. The unknown-hotel
edge-case check intentionally uses the fallback. The public S2 and Q4 replay
commands reproduce the selected candidate's net revenue.

To reproduce with the permitted `data/train.csv`, run `uv sync` and the context
training / rolling-probability commands under **Run the pipeline**, then:

```powershell
uv run python -m unittest discover -s tests
uv run python scripts/check_solution.py
uv run python scripts/simulate.py --stream year --readings stay_value --no-baselines --output artifacts/gap_diagnostics/review_year
uv run python scripts/simulate.py --stream s2 --readings stay_value --no-baselines --output artifacts/gap_diagnostics/review_s2
uv run python scripts/simulate.py --stream confirm --frozen --readings stay_value --no-baselines --output artifacts/gap_diagnostics/review_q4
```

Use new output directories to preserve the archived baseline. Original results
are tracked under `artifacts/simulate_year`, `artifacts/simulate_s2` and
`artifacts/simulate_confirm`; original code/config/bundle are at commit `09fa7f9`.
No new booking-level outputs or exploratory analysis scripts are included.

## Archived original results

Archived results with the original settings and calibration, our reconstruction
of the scorer, "cheapest" = lowest stay value (not the current defaults):

| Policy | `year` net | walks | `s2` net |
|---|---|---|---|
| Accept all | −€1.67M | 13,467 | −€1.66M |
| Simple capacity cap | €3.05M | 164 | €0.38M |
| Average-rate overbooking | €4.17M | 1,507 | €0.42M |
| **Our policy** | **€4.61M** | 313 | **€0.44M** |
| Greedy hindsight (lower bound of the ceiling) | €5.91M | 164 | €0.49M |

Original frozen October–December confirmation (S2 model, continuous July–December state,
reconstructed scorer, cheapest = lowest stay value):

| Policy | Net revenue | Walked guests |
|---|---:|---:|
| Accept all | €42,368 | 3,873 |
| Simple capacity cap | €787,100 | 215 |
| Average-rate overbooking | €1,068,190 | 436 |
| **Our policy** | **€1,261,492** | **255** |

Our policy earns **€193,302 more (+18.1%)** with **41.5% fewer walks** than
average-rate overbooking. Occupancy is 80.1%. The alternate nightly-rate reading
earns €1,243,504 with 237 walks; that sensitivity run changes both the scorer's
and policy's walk ordering. The primary frozen candidate uses stay value.

The saved checks reconcile all 14,378 booking rows, financial totals, hotel/month
aggregates and occupancy bounds. Config, source, data and model hashes stayed
unchanged. See `artifacts/simulate_confirm/summary.csv`, `verification.json`,
`frozen_config.json` and `run_manifest.json`. These checks do not independently
reconstruct seating carried over from July–September. The deployment model was
not used for confirmation because its calibration already includes October–December.

Weaknesses identified during the original tuning, before context calibration
and the current policy changes:

- **Downtown is under-filled in the `year` stream (73% occupancy).** The early
  rolling models had four months of history and rate Downtown guests far too
  likely to show (commitments: 58% predicted, 40% actual). The gap closes as
  history grows (Jul–Sep bookings: 72% predicted, 75% actual), so the Final
  model should behave better, but that is not measured. Raising `load_target`
  would look good in this stream and could over-accept in 2017.
- **On `s2` the price test costs money** (€440k with it, €474k without), while
  on `year` it earns €145k. It stays on because `year` resembles 2017.
- `price_mult` between 0.7 and 1.3 moved `year` by under €0.1M with no clear trend.

## Model and splits

The training loader rejects arrivals in 2017 or later. Never extract the
evaluation archive or fetch the public test data. The supplied local history
has 78,132 rows, with arrivals July 2015 through December 2016. `deposit` is
excluded when reading and never becomes a feature.


The periods in `src/hackathon/splits.py` use arrival dates and exclusive end
boundaries. Early booking dates do not make future arrivals eligible for training.

| Split | Train | Internal validation | Calibration | Tuning | Confirmation |
|---|---|---|---|---|---|
| S2, primary | Jul 2015–Mar 2016 | Feb–Mar 2016 | Apr–Jun 2016 | Jul–Sep 2016 | Oct–Dec 2016 |
| S1, diagnostic | Jul–Oct 2015 | Sep–Oct 2015 | Nov–Dec 2015 | None | None; 2016 replay is diagnostic |
| Final, deployment | Jul 2015–Sep 2016 | Aug–Sep 2016 | Oct–Dec 2016 | None | Official run only |

Model selection fits the portion before internal validation, compares combined
and separate hotel models there, then refits the selected model on its full
training period with frozen tree counts. Price references are fitted again on
that training period. Calibration uses only the designated calibration period.
Raw, sigmoid, and isotonic probabilities are compared on S2 tuning requests;
model selection does not score confirmation. For S1 or Final, supply an already chosen method,
for example `--split Final --calibration sigmoid`. Do this deployment fit after
the final system's confirmation; it intentionally uses October–December as
calibration and cannot provide an untouched S2 confirmation result.

The current S2 model artifacts are in `artifacts/cancellation_s2_context/`
(`artifacts/cancellation_s2/` preserves the original model). The deployment bundle in
`artifacts/final/` adds `demand.parquet`, the price tables, and `policy.json`:

- `model.json` and `model_*.cbm`: fitted features, calibration, models, and checksums.
- `metrics.json`: internal selection and tuning metrics, including hotel and lead-time slices.
- `calibration.png`: tuning calibration curves.
- `tuning_probabilities.csv`: `booking_id`, replay role, `p_cancel`, and `p_show`.
- `tuning_probabilities.manifest.json`: model and input fingerprints, plus the replay period.

The cache is rebuilt from its saved model, with a fresh group counter, and is
specific to that model and replay population. It contains no outcomes. Current
context replay models and generated analyses are local, ignored artifacts;
rerun the commands to recreate them. The final deployment bundle is tracked.

The prediction interface supports batch scoring and an online path without
constructing a DataFrame for every request:

```python
from hackathon.cancellation import CancellationModel
from hackathon.preprocessing import GroupCounter

model = CancellationModel.load("artifacts/cancellation_s2_context")
observed = GroupCounter()
p_cancel_commitments = model.p_cancel(commitments, state=observed)

# For EVERY incoming request, before the downstream accept/reject decision:
p_cancel = model.p_cancel_one(booking, state=observed)
p_show = 1.0 - p_cancel
```

Use a fresh counter for every replay. Commitments seed it in booking order; all
observed requests increment it, including rejected requests and the current
group member. Batch results preserve input order, even though group counting
scans `(booking_date, booking_id)`. Numeric missing values remain NaN, categorical
missing values become `_MISSING_`, and IDs such as `304`, `304.0`, and `"304"`
normalize identically. Price medians use training data only.

`hackathon.simulator.replay(history, Solution, start, end)` uses an **inclusive**
end date, creates one policy for both hotels, and strips outcomes before calling
it. It seats guests in arrival order, retains seated guests across their stays,
and walks the cheapest competing arrivals. Capacity before the replay is
reconstructed by seating the historical arrivals under an accept-all warm-up;
actual historical seating is unavailable. Explicit `initial_in_house` occupancy
can replace that assumption. Each scoring run rebuilds occupancy from scratch;
accepted sets never share cached occupancy.

The replay CLI compares accept-all, reject-all, simple capacity cap, average-rate
overbooking, and a feasible greedy hindsight lower bound. The average show rate
uses only outcomes known before replay start. Reports include revenue, penalties,
walks, acceptance, occupancy, hotel/month breakdowns, and individual decisions.
Both meanings of cheapest are reported by default. Use `--horizon truncate` to
test truncated stay values; the default counts full values and ignores capacity
beyond the supplied dates.

The completed confirmation froze the settings before replaying continuously from
July through December and reporting October–December. Policy state was not
restarted at October. The recorded command was (do not use reruns to tune):

```powershell
uv run python -u scripts/simulate.py --stream confirm --frozen --config artifacts/simulate_confirm/frozen_config.json --output artifacts/simulate_confirm
```

Original calibration comparison (validated on July–September 2016 requests).
The season labels `arrival_month`, `booking_month` and `arrival_week` are built
but not given to the model: with one or two years of history they memorise that
year's cancellation level. Removing them cut log loss from 0.581 to 0.477 and
raised AUC from 0.707 to 0.775 on 4,609 tuning requests; predicted cancellation
is now 24.1% against 24.3% observed (it was 17.2%). One combined model beat
separate hotel models there (0.485 vs 0.511 with sigmoid), and isotonic
calibration beat sigmoid and raw (0.477 / 0.485 / 0.505), so the original Final model
used combined + isotonic. That model still underpredicts cancellation on the whole
July–September population (22% vs 32%), which errs towards caution.
The subsequent frozen-policy October–December confirmation is reported above.
The current bundle replaces global isotonic calibration with a regularized
context calibration, fitted separately for each chronological training window.
Its policy uses `load_target=1.1`, `price_mult=0.85` and `raw_cap=4.0`; the
Monte Carlo revenue check still accounts for walk penalties.

Our reconstructed scorer shows substantial rule sensitivity on July–September:
accept-all earns net −€1.660M with cheapest stay-value ordering versus −€0.521M
with cheapest nightly-rate ordering. Existing commitments already overflow many
summer nights, explaining why the simple cap accepts only 0.7% of requests.
These figures include reconstructed carry-over occupancy and mandatory
commitments, unlike the earlier rough 2016 baselines in the plan.
