# Data Specification

The forecasting engine accepts a single CSV of daily market and macroeconomic
signals. This document is the contract. `src/forecasting_engine/ingest/schema.py`
is the machine-readable version of the same contract — if you change one, change
the other.

## File format

- UTF-8 encoded CSV with a header row
- One row per trading day, ascending by date
- No thousands separators, no currency symbols, no percent signs

## Columns

All columns are required.

| Column | Type | Range | Description |
|---|---|---|---|
| `date` | ISO date (`YYYY-MM-DD`) | — | Trading date. Unique, ascending. |
| `spx_close` | float | > 0 | S&P 500 index close |
| `agg_close` | float | > 0 | Bloomberg Global Aggregate Bond Index close |
| `vix` | float | 0 – 200 | CBOE Volatility Index |
| `credit_spread_hy` | float | 0 – 50 | ICE BofA US High Yield option-adjusted spread, percent |
| `credit_spread_ig` | float | 0 – 20 | ICE BofA US Investment Grade option-adjusted spread, percent |
| `fx_impl_vol` | float | 0 – 100 | G7 FX implied volatility index |
| `breakeven_10y` | float | -5 – 15 | 10-year inflation breakeven rate, percent |
| `term_spread` | float | -10 – 10 | 10-year minus 2-year Treasury yield, percent |

Percent columns are expressed in percentage points: a 3.5% spread is `3.5`, not
`0.035`.

## How violations are treated

Not every violation makes a file unusable. There are two classes.

**Rejected.** A missing column, an unparseable date, or a non-numeric value in a
numeric column. The file cannot be interpreted, so it is refused outright.

**Repaired and reported.** Out-of-order rows are sorted. Duplicate dates are
resolved by keeping the last occurrence, on the assumption that a repeated date
is a revision rather than a mistake. Values outside the ranges above are flagged
but retained — a genuine market dislocation looks a lot like an outlier, and
dropping it would hide exactly the events the model most needs to see.

No repair is silent. Every one is counted in the data quality report.

## What the system does with this file

Forward return targets are **derived, never supplied**. `spx_fwd_5d` and
`agg_fwd_5d` are computed from `spx_close` and `agg_close`. Do not add target
columns to the input. Unknown columns are ignored rather than rejected, so a
supplied target would be silently discarded rather than used.

Every signal column is shifted forward by at least one trading day before any
model sees it, so a row dated `t` carries the signal value observed at `t-1`.
This is applied centrally and cannot be bypassed.

## Missing values

Forward-fill only, capped at 5 consecutive days. Longer gaps are dropped and
reported. Backward-fill and interpolation are prohibited — both pull future
information into the past.

A signal that did not yet exist on a given date is missing, not zero. Do not
back-fill history for a series that started later; leave the cells empty.

## Point-in-time dating

Revised macroeconomic series must be dated to their **release date**, not their
reference period. CPI for March released on 10 April belongs on the row dated
10 April. FRED/ALFRED vintages provide this.

## Known-defect test file

`python -m forecasting_engine.fixtures` writes a synthetic file matching this
specification, including deliberate duplicates, a date gap, missing cells and a
crash window. Use it to exercise the quality checks. Pass `--clean` for a
defect-free file.
