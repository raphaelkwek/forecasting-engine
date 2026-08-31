# Data Specification

The forecasting engine accepts a single CSV of daily market and macroeconomic
signals. This document is the contract.

It is the shared reference for two pieces of work: the dashboard upload
component, which enforces the **file type** and **file size** rules below, and
schema validation (FYP-8), which enforces the **column** rules. When
`src/forecasting_engine/ingest/schema.py` exists it becomes the machine-readable
twin of the column contract — if you change one, change the other.

> **Status of the column contract.** Provisional. It cannot be finalised until
> the sponsor answers Q1 (which bond index) and Q2 (the forecast horizon) from
> the architecture design. Both are single config values rather than structural
> commitments. The file format, type and size rules are settled.

## File format

- UTF-8 encoded CSV with a header row
- One row per trading day, ascending by date
- No thousands separators, no currency symbols, no percent signs

## File type

`.csv` only. Any other extension is rejected on upload with an error naming the
extension we received.

A file named `.csv` whose contents do not parse as delimited text is rejected
the same way — renaming a spreadsheet does not make it a CSV. Export from Excel
or the Bloomberg Terminal using *Save As → CSV UTF-8*, not by changing the
filename.

## File size

**25 MB maximum** — 25,000,000 bytes. Files above this are rejected with an
error quoting both the file's size and the limit.

Decimal megabytes, not binary. Streamlit reports file sizes in decimal MB, and
matching it keeps the uploader and our error message from putting two different
numbers on the same file.

The limit is deliberately loose. The nine columns below at daily frequency come
to roughly 120 bytes per row, so thirty years of history is about 1 MB; a full
S&P 500 daily series back to 1928 with OHLCV is still under 4 MB. 25 MB is
around six times the largest file this contract can plausibly produce — large
enough that a legitimate export is never refused, small enough that uploading
the wrong file is caught immediately.

The enforced value is `MAX_UPLOAD_BYTES` in
`src/forecasting_engine/ingest/upload.py`. Changing the limit means changing
that constant, this section, and `server.maxUploadSize` in
`.streamlit/config.toml`, which is set above the limit on purpose so that our
error message is the one the user sees.

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

Not every violation makes a file unusable. There are two classes, and
`ingest/validation.py` enforces the split.

**Blocking.** A missing column, an unparseable date, or a non-numeric value in a
numeric column. The file cannot be interpreted, so validation fails and the
pipeline stops. The error names the column and, for a bad cell, the line number
as your spreadsheet numbers it — line 1 is the header, so the first data row is
line 2.

**Reported, not blocking.** Out-of-order rows are sorted. Duplicate dates are
resolved by keeping the last occurrence, on the assumption that a repeated date
is a revision rather than a mistake. Values outside the ranges above are flagged
but retained — a genuine market dislocation looks a lot like an outlier, and
dropping it would hide exactly the events the model most needs to see.

Dates must be ISO (`YYYY-MM-DD`). `01/02/2024` is rejected rather than guessed:
it means 1 February or 2 January depending on who exported it, and that is
precisely the ambiguity this contract exists to remove.

No violation is silent. Every one is counted in the data quality report, and
every validation run is recorded whether it passed or failed.

## What the system does with this file

Forward return targets are **derived, never supplied**. `spx_fwd_5d` and
`agg_fwd_5d` are computed from `spx_close` and `agg_close`. Do not add target
columns to the input — they will be rejected as unknown columns are ignored and
a supplied target would silently go unused.

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
