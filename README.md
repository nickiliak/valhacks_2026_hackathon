# Valhacks 2026

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1   # installs uv, Python 3.12 and deps into .venv
uv run python scripts/unpack.py                         # extract the kits to data/ (password at kick-off)
```

Add packages with `uv add <pkg>` (commit `pyproject.toml` + `uv.lock`). Skills: `.claude/skills/` (Claude Code), `.agents/skills/` (Codex).

The whole pipeline is implemented: chronological splits, shared preprocessing,
historical replay, a calibrated CatBoost cancellation model, nightly minimum
prices, the acceptance policy, and `scripts/solution.py`, which the organisers'
`evaluate(Solution)` can run. Settings are **not tuned yet** and the
October–December confirmation has **not been run**.

## Run the pipeline

From the repository root with the permitted, deposit-free `data/train.csv`:

```powershell
uv sync
uv run python -m unittest discover -s tests                            # 51 tests
uv run python scripts/train_cancel_model.py --split S2 --layout combined  # model for the Jul-Dec 2016 replays
uv run python scripts/rolling_probabilities.py                        # honest probabilities for a full-2016 replay
uv run python scripts/build_final.py                                  # deployment model + price tables -> artifacts/final
uv run python scripts/check_solution.py                               # dress rehearsal of scripts/solution.py
uv run python scripts/simulate.py --stream year                       # our policy vs baselines, with config/policy.json
```

`artifacts/` is git-ignored, so every machine must run these once (about six
minutes in total). `scripts/solution.py` loads `artifacts/final`; if that folder
is missing it prints a warning and uses a plain capacity rule instead of crashing.

| File | Role |
|---|---|
| `config/policy.json` | The policy settings and the model layout/calibration. `simulate.py` and `build_final.py` both read it, so what you simulate is what ships. Re-run `build_final.py` after changing it |
| `src/hackathon/policy.py` | `AcceptancePolicy` (the decision rule), `DemandHistory` (price tables), `RiskSim` (revenue-difference simulation), `thermometer`, `save_bundle` / `load_bundle` |
| `scripts/solution.py` | The official `Solution` class: loads the bundle and delegates to `AcceptancePolicy` |
| `scripts/simulate.py` | One run of the policy plus all baselines on a replay stream; saves decisions with reasons |
| `scripts/tune_policy.py` | Grid of settings on a stream, in parallel, e.g. `--stream year --set load_target=1.0,1.1 --set margin=0,0.1` |
| `scripts/check_solution.py` | Runs the real `Solution` on a 2017-shaped year: timing, crash and odd-input checks. Prints no revenue |
| `scripts/analysis/calibration_check.py` | Evidence for the calibration choices below |

## How a request is decided

1. **Show-up probability.** `p_show = 1 - p_cancel` from the calibrated model.
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
| `confirm` | Oct–Dec 2016, policy state carried on from 1 Jul | Untouched. `simulate.py --stream confirm --frozen`, once, after settings are frozen |

Results with the default settings, our reconstruction of the scorer, "cheapest" = lowest stay value:

| Policy | `year` net | walks | `s2` net |
|---|---|---|---|
| Accept all | −€1.67M | 13,467 | −€1.66M |
| Simple capacity cap | €3.05M | 164 | €0.38M |
| Average-rate overbooking | €4.17M | 1,507 | €0.42M |
| **Our policy** | **€4.61M** | 313 | **€0.44M** |
| Greedy hindsight (lower bound of the ceiling) | €5.91M | 164 | €0.49M |

Known weaknesses, in order of money at stake:

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
confirmation is not scored. For S1 or Final, supply an already chosen method,
for example `--split Final --calibration sigmoid`. Do this deployment fit after
the final system's confirmation; it intentionally uses October–December as
calibration and cannot provide an untouched S2 confirmation result.

The S2 model artifacts are in `artifacts/cancellation_s2/` (the deployment bundle in
`artifacts/final/` adds `demand.parquet`, the price tables, and `policy.json`):

- `model.json` and `model_*.cbm`: fitted features, calibration, models, and checksums.
- `metrics.json`: internal selection and tuning metrics, including hotel and lead-time slices.
- `calibration.png`: tuning calibration curves.
- `tuning_probabilities.csv`: `booking_id`, replay role, `p_cancel`, and `p_show`.
- `tuning_probabilities.manifest.json`: model and input fingerprints, plus the replay period.

The cache is rebuilt from its saved model, with a fresh group counter, and is
specific to that model and replay population. It contains no outcomes. Model
binaries and generated reports are local, ignored artifacts; rerun the commands
to recreate them.

The prediction interface supports batch scoring and an online path without
constructing a DataFrame for every request:

```python
from hackathon.cancellation import CancellationModel
from hackathon.preprocessing import GroupCounter

model = CancellationModel.load("artifacts/cancellation_s2")
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

For later confirmation, freeze the entire policy first, replay continuously from
July through December, and report October–December using `--report-start
2016-10-01`. Do not restart policy state at October. The equivalent baseline
command (not run during initial implementation) is:

```powershell
uv run python scripts/replay.py --start 2016-07-01 --end 2016-12-31 --report-start 2016-10-01 --output artifacts/replay_s2_confirmation
```

Calibration (validated on July–September 2016 requests, never on October–December).
The season labels `arrival_month`, `booking_month` and `arrival_week` are built
but not given to the model: with one or two years of history they memorise that
year's cancellation level. Removing them cut log loss from 0.581 to 0.477 and
raised AUC from 0.707 to 0.775 on 4,609 tuning requests; predicted cancellation
is now 24.1% against 24.3% observed (it was 17.2%). One combined model beat
separate hotel models there (0.485 vs 0.511 with sigmoid), and isotonic
calibration beat sigmoid and raw (0.477 / 0.485 / 0.505), so the Final model
uses combined + isotonic. Seaside still underpredicts cancellation on the whole
July–September population (22% vs 32%), which errs towards caution.
October–December remains unevaluated.

Our reconstructed scorer shows substantial rule sensitivity on July–September:
accept-all earns net −€1.660M with cheapest stay-value ordering versus −€0.521M
with cheapest nightly-rate ordering. Existing commitments already overflow many
summer nights, explaining why the simple cap accepts only 0.7% of requests.
These figures include reconstructed carry-over occupancy and mandatory
commitments, unlike the earlier rough 2016 baselines in the plan.
