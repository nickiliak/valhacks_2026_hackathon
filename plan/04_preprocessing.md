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
| Exclude from features | `booking_id`, `cancelled`, **`arrival_year`** (2017 unseen), `arrival_day` (noise), the raw date columns | Avoid meaningless or unseen inputs |
| Scaling / one-hot | None | Tree models don't need it |
| Unusual records (€5,400 rate, 40 adults) | Keep | Trees are robust; they are real bookings |
| `meal` | Map `Undefined` → `SC` | Same meaning |
| `nightly_rate = 0` | Keep in training; add flag `is_free`. The decision layer rejects them | They cancel differently; worthless to accept |
| Derived features | `stay_value = rate × nights`, `total_guests`, `has_kids`, `weekend_share = weekend_nights / nights`, `rate_vs_typical` (rate ÷ median rate for that hotel-month in training data) | Value, family, leisure vs business, "cheap for its season" |
| Group feature (**required** now that `deposit` is gone) | `block_size_so_far`: count of identical bookings (hotel, arrival_date, nights, agent, rate, room_type, sales_segment) seen so far, counting commitments and earlier `decide()` calls only. In training, compute it the same way in booking order | Blocks cancel together and are the main proxy for the former Non Refund signal; must never count future rows |
| `deposit` | **Does not exist.** Not in the data, not in any feature list | Dropped 14 Nov |
| Unseen categories in 2017 | CatBoost handles them; test the path explicitly with a made-up agent ID | New agents/companies will appear |

## Feature list (first version)
Categorical: `hotel`, `arrival_month`, `arrival_weekday`, `booking_month`, `meal`, `country`, `sales_segment`, `sales_channel`, `room_type`, `agent`, `company`, `guest_type`.
Numeric: `days_ahead`, `arrival_week`, `nights`, `weekend_nights`, `weekday_nights`, `weekend_share`, `adults`, `children`, `babies`, `total_guests`, `has_kids`, `returning_guest`, `past_cancellations`, `past_stays`, `amendments`, `waitlist_days`, `nightly_rate`, `rate_vs_typical`, `stay_value`, `special_requests`, `is_free`, `block_size_so_far`.

Variants to train for comparison: (a) without `country`; (b) without `amendments` + `special_requests` (honesty check); (c) without `agent` + `company` (robustness to new IDs in 2017).

## Leakage rules
- Allowed: every column in the booking row (the 2017 input has them all).
- Never: anything computed from rows with a later booking date, or from the outcome of a booking whose arrival is after the training cut-off.
