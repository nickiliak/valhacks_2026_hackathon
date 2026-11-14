# 04: Preprocessing (agreed)

## Principle: one function, three uses
`make_features(rows) -> table` must produce identical output for:
1. the training table (`train.csv`),
2. the `commitments` DataFrame at start-up,
3. a single booking `dict` in `decide()` (wrap into a one-row table, or better, a dict-based fast path that produces the same values).

If the three disagree, the model silently gets garbage in 2017. Test it: run the function on the same rows via all three paths and assert equality.

## Rules (team-agreed, combining ChatGPT's suggestion with our additions)
| Topic | Rule | Why |
|---|---|---|
| Numeric missing values | Keep as NaN. Don't fill with 0 | Tree models handle NaN natively; 0 can be a real value |
| Categorical columns | Convert to strings; missing → `"_MISSING_"`. `agent`/`company`: normalise `304.0` and `304` to `"304"` | train.csv has floats, the `decide()` dict may not. NaN for agent/company means "none", which is fine as a category |
| Dates | Parse both date columns to datetime (strings in train.csv, Timestamps in 2017). Derive `arrival_month`, `arrival_week`, `arrival_weekday`, `booking_month`, `booking_weekday`. Keep `days_ahead` | Season and weekday matter |
| Exclude from features | `booking_id`, `cancelled`, the raw date columns. **Default-excluded but worth a quick comparison:** `arrival_day` (probably noise; cheap to test on S2) and `arrival_year` (2017 is unseen; a tree would route it with the latest year seen, which could help or hurt; the only honest test is S1, train 2015 → test 2016) | Avoid meaningless or unseen inputs; test rather than assume when cheap |
| Scaling / one-hot | None | Tree models don't need it |
| Unusual records (€5,400 rate, 40 adults) | Keep | Trees are robust; they are real bookings |
| `meal` | Map `Undefined` → `SC` | Same meaning |
| `nightly_rate = 0` | Keep in training; add flag `is_free`. The decision layer rejects them | They cancel differently; worthless to accept |
| Derived features | `stay_value = rate × nights`, `total_guests`, `has_kids`, `weekend_share = weekend_nights / nights`, `rate_vs_typical` (rate ÷ median rate for that hotel-month in training data) | Value, family, leisure vs business, "cheap for its season" |
| Group feature (**required**) | `block_size_so_far`. **Key:** `(hotel, booking_date, arrival_date, nights, agent, nightly_rate, room_type, sales_segment)`; `booking_date` must be in the key (without it unrelated bookings merge; 02). **State:** a counter dict keyed by the block key, separate from the accepted-booking ledger. **Counting convention:** every *observed* request increments it, accepted or rejected (group size is a fact about demand, not about our choices); commitments are counted first at start-up in booking order; the current request **is included** (so a single booking has size 1). Training computes it with exactly the same convention by scanning rows in `(booking_date, booking_id)` order | Rows in blocks of 10+ cancel 67% vs 25% for singles (02); must never count future rows |
| `deposit` | **Does not exist.** Not in the data, not in any feature list | Dropped 14 Nov |
| Unseen categories in 2017 | CatBoost handles them; test the path explicitly with a made-up agent ID | New agents/companies will appear |

## Feature list (first version)
Categorical: `hotel`, `arrival_month`, `arrival_weekday`, `booking_month`, `booking_weekday`, `meal`, `country`, `sales_segment`, `sales_channel`, `room_type`, `agent`, `company`, `guest_type`.
Numeric: `days_ahead`, `arrival_week`, `nights`, `weekend_nights`, `weekday_nights`, `weekend_share`, `adults`, `children`, `babies`, `total_guests`, `has_kids`, `returning_guest`, `past_cancellations`, `past_stays`, `amendments`, `waitlist_days`, `nightly_rate`, `rate_vs_typical`, `stay_value`, `special_requests`, `is_free`, `block_size_so_far`.

Optional variants, only if time allows (the main model uses every permitted feature, `country` included; we are maximising revenue): (a) without `agent` + `company`, to see how much we depend on IDs that may be new in 2017; (b) without `amendments` + `special_requests`, as a talking point for the interviewer.

## Leakage rules
- Allowed: every column in the booking row (the 2017 input has them all).
- Never: anything computed from rows with a later booking date, or from the outcome of a booking whose arrival is after the training cut-off.
