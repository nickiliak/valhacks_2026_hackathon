# 02: Data overview (`data/train.csv`)

All numbers below were computed from `train.csv` on 14 Nov 2026 and independently re-checked by a reviewer. Where an earlier draft had a wrong number, the corrected value is given.

## Shape
- **78,132 rows**, 31 columns after dropping `deposit` (32 originally). One row = one booking request (one room; a group booking several rooms appears as several identical rows).
- **Arrivals:** 1 Jul 2015 → 31 Dec 2016 (data collection started 1 Jul 2015; the hotels run all year). **Booking dates:** from 18 Mar 2014.
- **Target:** `cancelled` (1 = cancelled or no-show, 0 = came).
- **Source:** the public "Hotel Booking Demand" dataset (Antonio, Almeida & Nunes 2019), two real hotels in Portugal, renamed: City → Downtown, Resort → Seaside. Knowing the source helps interpret columns; it does **not** permit reading its 2017 part.

## Headline numbers
| | Downtown | Seaside |
|---|---|---|
| Bookings | 51,575 | 26,557 |
| Rooms | 124 | 103 |
| Cancel rate | 41.5% | 26.6% |
| Avg nightly rate | €99 | €89 |
| Avg stay | 2.9 nights | 4.3 nights |
| Guests that actually showed, per night (avg) | 158 overall, **180 in 2016** | ~146 |
| Nights where shows > rooms | 71% overall, **85% in 2016** | ~79% |
| Cancel rate, H2 2015 → H2 2016 | 44% → 41% (excluding the former Non Refund rows: 27% → 32%) | 26% → 29% (21% → 27%) |

The last row shows **drift**: cancellation behaviour changed between years even among ordinary bookings. Our model can't observe 2017 behaviour, so some miscalibration in 2017 is likely.

## Columns
### Identity and target
| Column | Meaning | Use |
|---|---|---|
| `booking_id` | Row number | Not a feature |
| `hotel` | Downtown / Seaside | Feature; everything else is per hotel |
| `cancelled` | Target | Absent in 2017 |

### Timing
| Column | Meaning | Use |
|---|---|---|
| `booking_date` | Day booked (string in train.csv, Timestamp in 2017 input) | Decision order; booking month/weekday features |
| `arrival_date` | Day of arrival | Season, weekday |
| `arrival_year`, `arrival_month`, `arrival_week`, `arrival_day` | Arrival date split up | Month and week are useful. **Drop `arrival_year`** (2017 never seen). `arrival_day` is mostly noise |
| `days_ahead` | arrival − booking in days (verified exact) | **Strongest predictor** |
| `weekend_nights`, `weekday_nights`, `nights` | Length of stay (`nights` = sum, verified; no zero-night rows) | Stay value; how many nights a booking blocks |

### Guest
| Column | Meaning | Notes |
|---|---|---|
| `adults`, `children`, `babies` | Party size | `children` has 4 NaN. Odd values (40 adults) are groups |
| `country` | Guest nationality, 159 values, 395 missing | PRT cancels 64% vs 24% (Downtown), 44% vs 11% (Seaside); overall 57% vs 20%. Partly recorded at check-in, so PRT is also a stand-in for "unknown" |
| `returning_guest`, `past_stays`, `past_cancellations` | Guest history | Loyalty / serial-canceller signals |

### How they booked
| Column | Meaning | Notes |
|---|---|---|
| `sales_segment` | Online TA, Offline TA/TO, Groups, Direct, Corporate, Complementary, Aviation, Undefined | Groups cancel 70% at Downtown, 43% Seaside. Direct/Corporate 10–19% |
| `sales_channel` | Direct, Corporate, TA/TO, GDS, Undefined | Coarser |
| `agent`, `company` | IDs (284 / 297 values); NaN = none | Floats in train.csv (`304.0`); normalise to strings. 94% have no company |
| `guest_type` | Transient, Transient-Party, Group, Contract | |
| ~~`deposit`~~ | **Dropped from the data (14 Nov).** Not available to the solution and not used to justify anything | Feature choices rest on the permitted columns' own relationship to `cancelled` (see "Groups and duplicates" below) |
| `waitlist_days` | Days on waiting list | Mostly 0 |

### What they asked for
| Column | Meaning | Notes |
|---|---|---|
| `room_type` | Requested room type A–L | Capacity is one pool; type is a behaviour/price signal |
| `meal` | BB, HB, FB, SC, Undefined | SC = Undefined (no meal) |
| `special_requests` | 0–5 | 0 → 47% cancel; ≥1 → ~19% |
| `amendments` | Changes to the booking | 0 → 40%; ≥1 → 14–17%. Counted until check-in/cancellation in the source data |

### Money
| Column | Meaning | Notes |
|---|---|---|
| `nightly_rate` | € per night | Seaside Jan €48 vs Aug €192. **Same-month prices rose 35–55% from 2015 to 2016** (Downtown Jul €74→€115, Seaside Aug €156→€189). 933 rows at €0, max €5,400 |

## Lead time vs behaviour (2016)
| Booked ahead | Downtown cancel | Downtown rate | Seaside cancel | Seaside rate |
|---|---|---|---|---|
| 0 days | 9% | €100 | 5% | €69 |
| 1–7 | 14% | €107 | 7% | €75 |
| 8–30 | 31% | €114 | 21% | €93 |
| 31–90 | 39% | €107 | 33% | €96 |
| 91–180 | 46% | €105 | 39% | €101 |
| 181–365 | 66% | €88 | 35% | €86 |
| 365+ | 85% | €70 | 42% | €59 |

Late bookers pay more and show up. That's why rooms must be held back for them.

## Groups and duplicates (permitted columns only)
- **24,066 rows (31%) are exact duplicates** of another row (ignoring `booking_id`). They form 5,553 blocks covering 29,813 rows; **96.5% of those blocks share one outcome** (all cancelled or all showed).
- With the practical block key `(hotel, booking_date, arrival_date, nights, agent, nightly_rate, room_type, sales_segment)`: 45% of rows are in a block of ≥2; **90.7% of blocks share one outcome**; 6,943 blocks.
- Cancel rate by block size: single 25%; 2 rooms 28%; 3–4 rooms 29%; 5–9 rooms 38%; **10+ rooms 67%**.
- Dropping `booking_date` from the key merges unrelated bookings: shared outcome falls to 79%. Keep it in the key.
- Conclusion: block size is a strong, permitted predictor of cancellation, and block outcomes are **not independent**.

## The 2016 analog of the 2017 set-up
- 2016 arrivals: 56,290. Of those, **12,043 were booked before 2016-01-01** (the "commitments" analog) and **44,247 were booked during 2016** (the "decisions" analog).
- Commitments cancelled **54%**; in-year bookings 31%.
- Commitment show-ups filled ~15–60 rooms per night (up to ~110 counting bookings that later cancelled). Most of the year is decided by our yes/no answers.

## Columns partly recorded after booking (be honest about these)
`country` (confirmed at check-in), `amendments`, `special_requests`. The 2017 input rows contain them too, so using them is within the rules. In a live deployment some of this would be unknown at booking time. We report model quality with and without them.
