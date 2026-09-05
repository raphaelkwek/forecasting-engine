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

## Producing this file from Bloomberg

Bloomberg exports one workbook per security, which is not this format. See
[bloomberg-exports.md](bloomberg-exports.md) for the securities to pull and the
converter that joins them into one CSV.

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

Only `date`, `spx_close` and `vix` are **required** — a file missing any of
them cannot be used and is rejected. The other signal columns are **optional**:
the engine runs on whatever subset is present, and a missing optional column is
reported as informational rather than blocking. This lets the engine run on a
small set of signals before every feed is wired in.

| Column | Type | Range | Required | Description |
|---|---|---|---|---|
| `date` | ISO date (`YYYY-MM-DD`) | — | yes | Trading date. Unique, ascending. |
| `spx_close` | float | > 0 | yes | S&P 500 index close |
| `spx_close_target` | float | > 0 | no | S&P 500 close at date *t*, unlagged — the level the model's target return is computed from (derived, never supplied) |
| `vix` | float | 0 – 200 | yes | CBOE Volatility Index |
| `bond_index_global_agg` | float | > 0 | no | Bloomberg Global Aggregate Bond Index close (auto-sourced from Yahoo; may be overridden) |
| `bond_index_target` | float | > 0 | no | Bloomberg Global Aggregate close at date *t*, unlagged — the level the model's bond target return is computed from (derived, never supplied) |
| `tnx_close` | float | 0 – 20 | no | 10-year Treasury yield, percent |
| `dollar_index` | float | 50 – 170 | no | US Dollar Index (DXY) |
| `eur_fx_vol` | float | 0 – 200 | no | Euro FX implied volatility |
| `credit_spread_ig` | float | 0 – 50 | no | US IG credit spread (Moody's Baa less 10y Treasury), percent |
| `credit_spread_hy` | float | 0 – 50 | no | US high-yield OAS, percent |
| `breakeven_5y` | float | -5 – 15 | no | 5-year inflation breakeven rate, percent |
| `breakeven_10y` | float | -5 – 15 | no | 10-year inflation breakeven rate, percent |
| `term_spread` | float | -10 – 10 | no | 10-year minus 2-year Treasury yield, percent |
| `fx_impl_vol` | float | 0 – 100 | no | G7 FX implied volatility index |
| `ff_mkt_rf` | float | — | no | Fama-French market risk premium (Mkt-RF), percent |
| `ff_smb` | float | — | no | Fama-French small-minus-big factor, percent |
| `ff_hml` | float | — | no | Fama-French high-minus-low factor, percent |
| `ff_rmw` | float | — | no | Fama-French robust-minus-weak factor, percent |
| `ff_cma` | float | — | no | Fama-French conservative-minus-aggressive factor, percent |
| `ff_rf` | float | — | no | Fama-French risk-free rate, percent |

Percent columns are expressed in percentage points: a 3.5% spread is `3.5`, not
`0.035`.

## How violations are treated

Not every violation makes a file unusable. There are two classes, and
`ingest/validation.py` enforces the split.

**Blocking.** A missing *required* column (`date`, `spx_close`, `vix`), an
unparseable date, or a non-numeric value in a numeric column. The file cannot be
interpreted, so validation fails and the pipeline stops. The error names the
column and, for a bad cell, the line number as your spreadsheet numbers it —
line 1 is the header, so the first data row is line 2. A missing *optional*
signal column is reported but does not block.

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

Forward return targets are **derived, never supplied**. Extraction (and
synthetic generation) keep two **unlagged** price columns — `spx_close_target`
(S&P 500 close) and `bond_index_target` (Bloomberg Global Aggregate close) —
carrying the value observed at date *t*. The model's target return is computed
from consecutive observed levels, `spx_close_target[t+1] / spx_close_target[t] - 1`
and the same for `bond_index_target`. Do not add target columns to the input:
they are created during extraction (or synthesis) and a supplied target would
silently go unused.

Every *signal* column is shifted forward by at least one trading day before any
model sees it, so a row dated `t` carries the signal value observed at `t-1`.
The two `*_target` columns are the exception — they stay as the raw observed
levels at `t`, because lagging them would shift the very observation the
forecast is measured against. Both the lag and the unlagged target columns are
applied centrally by the extraction step and cannot be bypassed.

## Missing values

Forward-fill only, capped at 5 consecutive days. Longer gaps are dropped and
reported. Backward-fill and interpolation are prohibited — both pull future
information into the past.

A signal that did not yet exist on a given date is missing, not zero. Do not
back-fill history for a series that started later; leave the cells empty.

### What counts as blank

An empty cell is missing data. So are `NA`, `N/A`, `n/a`, `null`, `NULL`, `nan`
and `#N/A` — including Bloomberg's `#N/A N/A`, which its exports use freely.
These are reported as missing and do not block validation.

Anything else in a numeric column is a type error and blocks: `-`, `TBD`,
`not reported`, and Bloomberg's longer forms `#N/A Field Not Applicable` and
`#N/A Invalid Security` are all rejected with their line number. If your export
carries those, replace them with empty cells before uploading.

The distinction matters and is invisible in Excel — both look like text in a
number column. Missing data is a fact about the world; a placeholder we cannot
interpret is a fault in the file.

## Synthetic test file

`python -m forecasting_engine.fixtures` writes a file matching this
specification, for exercising the pipeline before the real exports are
complete:

```bash
uv run python -m forecasting_engine.fixtures --years 10
```

It includes deliberate defects — duplicate dates, a four-day gap, blank cells —
and a stress window a third of the way through, so the quality checks and the
crash-recall metric have something to find. Pass `--clean` for a file with none
of them. Output is deterministic for a given `--seed`.

The numbers are invented. They are shaped to behave like a market — volatility
mean-reverts and spikes as prices fall, spreads widen with it — but nothing in
the file came from one. It is for testing and demonstration, never for analysis
or for any result presented as real.

## Point-in-time dating

Revised macroeconomic series must be dated to their **release date**, not their
reference period. CPI for March released on 10 April belongs on the row dated
10 April. FRED/ALFRED vintages provide this.
