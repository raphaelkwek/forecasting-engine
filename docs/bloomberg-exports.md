# Exporting the signal data from Bloomberg

The engine wants one CSV matching [the data specification](data-specification.md).
Bloomberg exports one file per security. This document says which securities
to pull, and how to turn the pile of exports into that one CSV.

## What to export

One export per row below, as either a CSV or a workbook. Both carry the same
two things the converter reads: a `Date` column with the field beside it, and
a metadata block whose `Security` entry names the ticker. That is the default
shape of a Bloomberg history export, so nothing special is required — but the
**`Security` value in the metadata is what the converter reads**, not the
filename. A file named after the right ticker but holding the wrong one is the
failure this has already hit once.

A CSV export is the metadata block, a blank line, then the table:

```
Security,SPX Index
Start Date,1/1/2016
End Date,12/31/2025
Period,Daily

Date,PX_LAST,PX_BID
1/4/2016,2012.66,#N/A N/A
```

A workbook export holds the same table on a `Data` sheet and the metadata on a
`Metadata` sheet.

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

**CSV exports** go in through the dashboard. On the **Data** page choose
*Bloomberg exports*, drop every file in at once, and the page joins them on
date, maps each security onto its contract column, and passes the result to
the same schema validation and quality report as a file uploaded directly. It
names what it could not place — a security the contract does not ask for, a
near miss like `LF98TRUU`, a file with no `PX_LAST` — and which signals still
have no export. Nothing needs a command line.

**Dates in a CSV export** are `m/d/yyyy` or `d/m/yyyy` depending on the
terminal's locale, and for any day up to the 12th the two look the same. The
reader settles the order once per file from every date in it, the metadata's
start and end dates included: a day above 12 anywhere decides it, and a file
with none is read month first, Bloomberg's default. A file that mixes the two
is refused rather than guessed. If a merged file's dates look a month out,
check the terminal's date format setting.

**Workbook exports** have a command-line converter that does the same join.
Point it at the folder holding the workbooks — the shell expands the `*.xlsx`,
so give it a real directory rather than copying this line verbatim:

```bash
uv run python -m forecasting_engine.convert ~/Documents/FYP/exports/*.xlsx -o data/signals.csv
```

If the shell answers `no matches found`, that path has no `.xlsx` files in it.

Close the workbooks in Excel first, or don't worry about it — Excel leaves a
lock file named `~$something.xlsx` beside any workbook it has open, and the
converter names and skips those rather than choking on them. Anything else that
is not a readable workbook is reported the same way, so one bad file never costs
you the good ones.

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
