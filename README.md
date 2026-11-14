# Valhacks 2026

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1   # installs uv, Python 3.12 and deps into .venv
uv run python scripts/unpack.py                         # extract the kits to data/ (password at kick-off)
```

Add packages with `uv add <pkg>` (commit `pyproject.toml` + `uv.lock`). Skills: `.claude/skills/` (Claude Code), `.agents/skills/` (Codex).

The first four stages are implemented: chronological splits, shared preprocessing,
historical replay, and a trained CatBoost cancellation model. The pricing, risk
ledger, and final acceptance policy are subsequent stages; `scripts/solution.py`
is still the organiser's interface template.

Run from the repository root with the permitted, deposit-free `data/train.csv`:

```powershell
uv sync
uv run python -m unittest discover -s tests -v
uv run python scripts/train_cancel_model.py --split S2
uv run python scripts/replay.py --output artifacts/replay_s2
```

Both commands default to tuning data only. The training loader rejects arrivals
in 2017 or later. Never extract the evaluation archive or fetch the public test
data. The supplied local history has 78,132 rows, with arrivals July 2015 through
December 2016. `deposit` is excluded when reading and never becomes a feature.

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

The default model artifacts are in `artifacts/cancellation_s2/`:

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

Initial verification: 43 tests pass, covering chronology, feature parity,
calibration persistence, cache provenance, and hand-calculated seating scenarios.
The trained S2 model selected separate hotel models and sigmoid calibration.
On 4,609 tuning requests, log loss is 0.5813, Brier score 0.1767, and AUC 0.7072.
Calibration still underpredicts cancellations (17.2% predicted versus 24.3%
observed); these are tuning results, not final performance claims. Online
inference took 2.25 seconds for those requests; batch, online, and cached
probabilities matched exactly. October–December remains unevaluated.

Our reconstructed scorer shows substantial rule sensitivity on July–September:
accept-all earns net −€1.660M with cheapest stay-value ordering versus −€0.521M
with cheapest nightly-rate ordering. Existing commitments already overflow many
summer nights, explaining why the simple cap accepts only 0.7% of requests.
These figures include reconstructed carry-over occupancy and mandatory
commitments, unlike the earlier rough 2016 baselines in the plan.
