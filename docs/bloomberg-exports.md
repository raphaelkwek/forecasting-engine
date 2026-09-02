# Exporting the signal data from Bloomberg

The engine wants one CSV matching [the data specification](data-specification.md).
Bloomberg exports one workbook per security. This document says which securities
to pull, and how to turn the pile of workbooks into that one CSV.

## What to export

One workbook per row below, each with a `Data` sheet (`Date` plus the field) and
a `Metadata` sheet whose `Security` row names the ticker. That is the default
shape of a Bloomberg history export, so nothing special is required — but the
**`Security` value in the metadata is what the converter reads**, not the
filename. A workbook named after the right ticker but holding the wrong one is
the failure this has already hit once.

| Contract column | Bloomberg security | Field |
|---|---|---|
| `spx_close` | `SPX Index` | `PX_LAST` |
| `agg_close` | `LEGATRUU Index` | `PX_LAST` |
| `vix` | `VIX Index` | `PX_LAST` |
| `credit_spread_hy` | **`LF98OAS Index`** | `PX_LAST` |
| `credit_spread_ig` | `LUACOAS Index` | `PX_LAST` |
| `fx_impl_vol` | **`JPMVXYG7 Index`** | `PX_LAST` |
| `breakeven_10y` | `USGGBE10 Index` | `PX_LAST` |
| `term_spread` | `USGG10YR Index` **and** `USGG2YR Index` | `PX_LAST` |

`term_spread` has no ticker of its own — it is the 10-year yield minus the
2-year. Export both legs and the converter takes the difference.

### Three easy mistakes

**`LF98OAS` versus `LF98TRUU`.** `LF98TRUU` is the US High Yield *total return*
index; its values run in the thousands. `LF98OAS` is the option-adjusted spread,
a few percent. The contract wants the spread. The tell is behaviour in a crisis:
in March 2020 a spread spikes, while a total return index falls to a low.

**`JPMVXYG7` versus `JPMVXYGL`.** `G7` is the G7 basket the contract specifies;
`GL` is the broader global index. Both are plausible volatility numbers, so
neither the value range nor a range check will catch the wrong one — only the
metadata will.

**Total return versus price for `SPX`.** Export `PX_LAST`. A workbook holding
only `TOT_RETURN_INDEX_GROSS_DVDS` has no `PX_LAST` column and is skipped.

## Converting

Point it at the folder holding the workbooks — the shell expands the `*.xlsx`,
so give it a real directory rather than copying this line verbatim:

```bash
uv run python -m forecasting_engine.convert ~/Documents/FYP/exports/*.xlsx -o data/signals.csv
```

If the shell answers `no matches found`, that path has no `.xlsx` files in it.

Output goes under `data/` because that directory is gitignored; exported market
data should not end up in the repository.

It reads the `Data` sheet of each workbook, takes `PX_LAST`, joins everything on
date, and writes the CSV in contract column order with ISO dates. Then upload
`signals.csv` on the dashboard's Data page.

The command prints what it did and exits non-zero if the result will not pass
validation, naming every signal it could not supply and, where it recognises the
ticker, what to export instead:

```
Wrote 2,610 rows covering 5 of 8 signals.
  ok       agg_close          LEGATRUU Index
  ...
  skipped  credit_spread_Data_LF98OAS_Index__values.xlsx: LF98TRUU Index is the
           high yield total return index, not its spread — re-export LF98OAS
           Index for credit_spread_hy
  MISSING  term_spread        no export supplied this
```

It writes the file regardless, so a partial CSV can still be inspected and
uploaded — validation will then name the missing columns.

### What it does not do

**Gaps are left as gaps.** Different indices keep different trading calendars.
Across a real ten-year pull the union was 2,610 dates with all signals present
on only 2,499 of them — `spx_close` missing 97, `vix` 65, the spreads around 80.
Those cells are left empty, which the contract treats as missing data. Filling
them here would hide from the data quality report the very thing it exists to
report; forward-filling happens later, capped and counted.

**Range breaches are flagged, not corrected.** If almost every value in a column
falls outside its documented range, the converter says so — that pattern means
the wrong field was exported. A handful of breaches is left alone, because a
genuine market dislocation looks a lot like an outlier.
