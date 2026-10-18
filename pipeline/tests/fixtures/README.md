# AMPds2 loader fixtures

These small, synthetic files define the Task 1 data contract without copying rows from AMPds2. They use the exact `Electricity_WHE.csv` header unless the case intentionally tests a wrong schema. Timestamps begin at `1640995200`, which is `2022-01-01T00:00:00Z`.

[`cases.json`](cases.json) is the machine-readable expectation list. Expected energy values were calculated independently from the intended loader:

```text
energy_Wh = sum of 60 one-minute P values in watts / 60
```

The result is rounded once with decimal round-half-up. Individual samples are never rounded.

## Valid conversion cases

| Fixture | Literal input | Expected result |
| --- | --- | --- |
| `valid_60w_hour.csv` | 60 consecutive minute samples at 60 W | `60 × 60 / 60 = 60 Wh` |
| `fractional_0_5w_hour.csv` | 60 consecutive minute samples at 0.5 W | `60 × 0.5 / 60 = 0.5 Wh`, exact tie, rounds to `1 Wh`; catches integer-only parsing |
| `rounding_boundaries.csv` hour 0 | 29 samples at 1 W and 31 at 0 W | `29/60 Wh`, below 0.5, rounds to `0 Wh` |
| `rounding_boundaries.csv` hour 1 | 30 samples at 1 W and 30 at 0 W | `30/60 = 0.5 Wh`, exact tie, rounds to `1 Wh` |
| `rounding_boundaries.csv` hour 2 | 31 samples at 1 W and 29 at 0 W | `31/60 Wh`, above 0.5, rounds to `1 Wh` |
| `imputed_hour.csv` | 60 samples at 60 W; minute 17 has a leading `+` timestamp | `60 Wh`, one retained imputed sample |
| `partial_edges.csv` | 30 leading rows, one complete 60-row hour, 30 trailing rows | emit the middle `60 Wh` hour; count 60 excluded rows across two boundary hours |

## Required rejection cases

| Fixture | Deliberate defect | Expected rejection |
| --- | --- | --- |
| `duplicate_timestamp.csv` | Timestamp `1640996400` appears twice | duplicate timestamp with row context |
| `gap_hour.csv` | A damaged hour missing minute 30 is surrounded by two complete hours | internal gap at `1640997000`; surrounding complete hours prevent a generic empty-result rejection from satisfying this case |
| `out_of_order.csv` | Minutes 20 and 21 are swapped | reversed/out-of-order timestamp |
| `negative_power.csv` | Minute 12 has `P = -1` | unsupported negative consumption value |
| `non_finite_power.csv` | Minute 8 has `P = NaN` | non-finite power value |
| `missing_power.csv` | Minute 9 has an empty `P` | missing power value |
| `invalid_timestamp.csv` | Source row 9 has `unix_ts = not-a-timestamp` | invalid timestamp with source-row context |
| `wrong_schema.csv` | Uses `timestamp,power` | exact-schema mismatch |
| `empty.csv` | Header only | no readings / empty result |

Run `python3 pipeline/tests/fixtures/validate_contract.py` from the repository root to validate the literal definitions, independently calculated results, selected real-data window and unchanged source checksums. These files specify future Task 4 behavior; their presence does not claim the current loader implements it. Task 4 tests should use the literal expectations in `cases.json` rather than derive expected results by calling the loader itself.
