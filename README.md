# Hotel booking accept/reject system

Valhacks 2026 (DTU Skylab, organised by BEST Copenhagen, sponsored by Accenture).
Two hotels (124 and 103 rooms) receive booking requests one at a time, and our
code answers accept or reject. The score is the revenue of guests who show up and
get a room, minus 2.5 times the stay value of every guest we have to relocate
because the hotel is full.

Our approach in one line: **never reject someone for being likely to cancel;
count each booking as the fraction of a room it is expected to use, keep rooms
for later, higher-paying guests, and accept only when simulated net revenue
goes up.**

| Layer | What it does | Where |
|---|---|---|
| Show-up model | CatBoost estimates each booking's chance of arriving, calibrated on later months | `src/hackathon/cancellation.py` |
| Ledger and minimum prices | Expected rooms used per night; a minimum rate per night from what later bookers paid a year earlier | `src/hackathon/policy.py` |
| Revenue simulation | 200 random show-up scenarios with and without the request; accept if average net revenue rises | `src/hackathon/policy.py` |
| Replay simulator | Our reconstruction of the scorer, for testing on past bookings | `src/hackathon/simulator.py` |

## Result

On a replay of October–December 2016 (our reconstruction of the scorer) the final
version earns **€1.348M net**: 26% above average-rate overbooking and 83% of the
proven hindsight optimum (€1.632M). That period had been inspected before the
last changes, so it is a development check. An earlier frozen version, scored
once on untouched months, was 18% ahead of the same baseline. Full tables are
under "Results of the final version" below.

The hackathon has ended and the organisers did not publish scores, so there is no
official number; the replay figures are the only evidence. In the judging the
technical work was not examined, and our presentation (two slides, no live demo)
is where we fell short. If you reuse this: settle the pitch format early, and
build a short live demo from `scripts/simulate.py`, which already records a
readable reason for every decision.

## Setup

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1   # installs uv, Python 3.12 and deps into .venv
uv run python scripts/unpack.py                         # extract the kits to data/ (password at kick-off)
```

Add packages with `uv add <pkg>` (commit `pyproject.toml` + `uv.lock`). The
training data (`data/train.csv`) is not in the repository. Never use the 2017
evaluation data; reading it is against the rules.

The pipeline is complete: chronological splits, shared preprocessing, historical
replay, the calibrated CatBoost model, nightly minimum prices, the acceptance
policy, and `scripts/solution.py`, which the organisers' `evaluate(Solution)` can run.

## Run the pipeline

From the repository root with the permitted, deposit-free `data/train.csv`:

```powershell
uv sync
uv run python -m unittest discover -s tests                                      # 53 tests
uv run python scripts/train_cancel_model.py --split S2 --layout combined --extend --half-life 180   # model for the Jul-Dec 2016 replays
uv run python scripts/rolling_probabilities.py --extend --half-life 180          # honest probabilities for a full-2016 replay
uv run python scripts/build_final.py                                             # deployment model + price tables -> artifacts/final
uv run python scripts/check_solution.py                                          # dress rehearsal of scripts/solution.py
uv run python scripts/simulate.py --stream year                                  # our policy vs baselines, with config/policy.json
```

`artifacts/` is tracked in git, so after a pull `scripts/solution.py` works
without retraining; the commands above recreate everything (about ten minutes).
`scripts/solution.py` loads `artifacts/final`; if that folder is missing it
prints a warning and uses a plain capacity rule instead of crashing.

| File | Role |
|---|---|
| `config/policy.json` | The policy settings and the model recipe. `simulate.py` and `build_final.py` both read it, so what you simulate is what ships. Re-run `build_final.py` after changing it |
| `src/hackathon/policy.py` | `AcceptancePolicy` (the decision rule), `DemandHistory` (price tables), `RiskSim` (revenue-difference simulation), `thermometer`, `save_bundle` / `load_bundle` |
| `scripts/solution.py` | The official `Solution` class: loads the bundle and delegates to `AcceptancePolicy` |
| `scripts/simulate.py` | One run of the policy plus all baselines on a replay stream; saves decisions with reasons |
| `scripts/tune_policy.py` | Grid of settings on a stream, in parallel, e.g. `--stream year --set load_target=1.0,1.1 --set margin=0,0.1` |
| `scripts/check_solution.py` | Runs the real `Solution` on a 2017-shaped year: timing, crash and odd-input checks. Prints no revenue |
| `scripts/analysis/calibration_check.py` | Evidence for removing the season labels |
| `scripts/analysis/model_recency_check.py` | Evidence for training on the newest months and weighting recent bookings |
| `scripts/analysis/empty_rooms.py` | Which rule rejected guests who would have fitted into rooms that stayed empty |
| `pitch/` | The two-slide deck (`.pptx` and `.pdf`), the speaker script with likely questions, and the scripts that build it |
| `scripts/analysis/stress_test.py` | What happens to revenue and walks if the probabilities are wrong |

## How a request is decided

1. **Show-up probability.** `p_show = 1 - p_cancel` from the calibrated model.
2. **Ledger.** Per hotel night, the sum of `p_show` over held bookings = expected rooms used.
3. **Guardrails.** Reject free rooms; reject if held bookings on a night would exceed `raw_cap` x hotel rooms.
4. **Minimum price.** For each night we take the guests who actually stayed on the
   same weekday one year earlier (plus the week before and after) and who booked
   later than today. Sorted by rate, they show what the rooms still free are
   worth: the minimum price is the rate of the first of them who would no longer
   fit. The request must pay at least the average minimum over its nights. On a
   night that is already full in expectation the price test steps aside and
   step 5 decides alone.
   Last year's rates are scaled to this year. The scale starts from the
   commitments on hand versus those on hand a year earlier, and is re-measured
   every week from the requests seen so far: what guests are asking to pay for
   each arrival month against what they paid by the same date last year
   (`live_scale`). Rejected requests count too; no outcomes are used.
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
| `s2` | Jul–Sep 2016 from 1 Jul | Commitments alone overfill it (reject-all still walks 2,429 guests), so it mostly tests displacement |
| `confirm` | Oct–Dec 2016, policy state carried on from 1 Jul | Scored once with frozen settings (`artifacts/simulate_confirm`). Since inspected, so later runs are development checks (`artifacts/simulate_q4_development`) |

## Results of the final version

Our reconstruction of the scorer, "cheapest" = lowest stay value. The final
version was chosen on the first two columns; October–December was run afterwards.

| Policy | `year` net | `year` walks | `s2` net | Oct–Dec net | Oct–Dec walks |
|---|---|---|---|---|---|
| Accept all | −€1.67M | 13,467 | −€1.66M | €0.04M | 3,873 |
| Simple capacity cap | €3.05M | 164 | €0.38M | €0.79M | 215 |
| Average-rate overbooking | €4.17M | 1,507 | €0.42M | €1.07M | 436 |
| Frozen version (confirmed 14:57) | €4.61M | 313 | €0.44M | €1.261M | 255 |
| **Final version** | **€4.93M** | 363 | **€0.46M** | **€1.348M** | 288 |
| Greedy hindsight (lower bound of the ceiling) | €5.91M | 164 | €0.49M | €1.53M | 215 |
| Proven hindsight optimum (solver, Oct–Dec only) | | | | €1.632M | 232 |

Under the other reading of "cheapest" (lowest nightly rate) the final version
earns €4.95M, €0.95M and €1.339M.

What changed between the frozen and the final version, and what each added on `year`:

| Change | `year` net |
|---|---|
| Frozen version | €4.61M |
| + price scale re-measured weekly from the requests seen (`live_scale`) | €4.67M |
| + trees also trained on the calibration months (`extend`) | €4.87M |
| + recent bookings weighted more (`half_life` 180 days) | €4.93M |
| + long-stay bookkeeping fix in the simulation (from the improvement branch) | unchanged |

No policy setting was changed: `load_target`, `price_mult`, `margin` and
`raw_cap` are still the defaults.

**Why not greedier or more cautious.** `scripts/analysis/stress_test.py` feeds
the policy deliberately wrong probabilities. On October–December (net in € million, walks in brackets):

| Policy's belief about show-ups | Default settings | Greedier (`load_target` 1.1, `price_mult` 0.85, `raw_cap` 4) |
|---|---|---|
| Far too low (about 35 points) | 1.17 (1,029) | 0.85 (1,821) |
| Too low (about 13 points) | 1.35 (476) | 1.31 (767) |
| Correct | 1.35 (288) | 1.38 (339) |
| Too high (about 10 points) | 1.26 (247) | 1.31 (241) |

The defaults lose little in either direction. Greedier settings gain 2% when the
model is right and lose far more when it is badly wrong; on `year` and `s2` they
gain nothing with the final model. Extra caution (`margin` 0.15 or
`logit_noise` 0.5) changed every cell by under 1%.

**The improvement branch** (`improve/booking-revenue-20261114`) reaches similar
net revenue (€4.95M / €0.46M / €1.335M) with a context calibrator and the
greedier settings above, at twice the walks on `year` (752). Its long-stay fix,
regression test and solver ceiling are used here; its calibrator and settings
are not. Both versions learn from the same calibration months, so they should
not be combined.

Known weaknesses:

- **No independent confirmation of the final version.** October–December was
  not used to choose it, but it had been inspected before.
- **The model we ship cannot be tested.** It is trained on all 18 months; every
  replay uses a stand-in trained on less.
- **Downtown is still under-filled in the `year` stream (78% occupancy)**
  because the early rolling models see little history. On October–December,
  with nine months of history, accepted guests were predicted to show at 67%
  (Downtown) and 85% (Seaside) and 65% and 82% did.
- **The stress test shifts all probabilities the same way.** A model that is
  wrong for one kind of guest only is not covered.
- **`half_life` 180 was picked from three values** on model metrics and checked
  once in money.

## Archived: frozen confirmation of the earlier version

Frozen October–December confirmation (S2 model, continuous July–December state,
reconstructed scorer, cheapest = lowest stay value), run once at 14:57 with the
settings and model of commit `09fa7f9`:

| Policy | Net revenue | Walked guests |
|---|---:|---:|
| Accept all | €42,368 | 3,873 |
| Simple capacity cap | €787,100 | 215 |
| Average-rate overbooking | €1,068,190 | 436 |
| **Frozen version** | **€1,261,492** | **255** |

It earned **€193,302 more (+18.1%)** than average-rate overbooking. The saved
checks reconcile all 14,378 booking rows, financial totals, hotel/month
aggregates and occupancy bounds; see `artifacts/simulate_confirm`. The model
files of that version were replaced by the final ones; recover them from commit
`09fa7f9` if needed.

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

The completed confirmation froze the settings before replaying continuously from
July through December and reporting October–December. Policy state was not
restarted at October. The recorded command was (do not use reruns to tune):

```powershell
uv run python -u scripts/simulate.py --stream confirm --frozen --config artifacts/simulate_confirm/frozen_config.json --output artifacts/simulate_confirm
```

Model choices, each validated on July–September 2016 requests (4,609 rows):

| Step | Log loss | AUC | Predicted / actual cancellation |
|---|---|---|---|
| First model, with season labels, per-hotel, sigmoid | 0.581 | 0.707 | 17.2% / 24.3% |
| Season labels removed, one combined model, isotonic (frozen version) | 0.477 | 0.775 | 24.1% / 24.3% |
| Trees also trained on the calibration months, half-life 180 days, sigmoid (final) | 0.434 | 0.818 | 25.6% / 24.3% |

- **Season labels** (`arrival_month`, `booking_month`, `arrival_week`) are built
  but not given to the model: with one or two years of history they memorise
  that year's cancellation level.
- **Extended training.** The calibrator is fitted on the first model's
  predictions for the calibration months, which that model never saw. The trees
  are then refitted with the same recipe on training + calibration months and
  the calibrator is kept. The newest months shape the model without it being
  calibrated on rows it trained on.
- **Recency weighting.** A training row's weight halves for every 180 days of age.
- The Final model applies the same recipe one step later: calibrator from a
  model trained to September 2016 and applied to October–December, trees
  refitted on all 18 months.

Our reconstructed scorer shows substantial rule sensitivity on July–September:
accept-all earns net −€1.660M with cheapest stay-value ordering versus −€0.521M
with cheapest nightly-rate ordering. Existing commitments already overflow many
summer nights, explaining why the simple cap accepts only 0.7% of requests.
These figures include reconstructed carry-over occupancy and mandatory
commitments, unlike the earlier rough 2016 baselines in the plan.
