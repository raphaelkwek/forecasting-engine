# Ingestion consolidation: one converter, one validator, one of each check

By early September 2026 the repository held two validation layers, two outlier
methods, two calendar approaches and three ways to get data in, spread across
`main` and three branches. This document records which one survives in each
case and the evidence behind the choice, so that nobody rebuilds the losing
side. Every number below was measured on the branches as they stood on
7 September 2026; the comparison script is not kept, the numbers are.

## What was duplicated

| Concern | `main` | Bloomberg CSV branch | Yahoo/FRED branch |
|---|---|---|---|
| Data input | `.xlsx` converter at the command line | CSV multi-file merge in the app | Yahoo Finance, FRED, Ken French pulls |
| Validation | `ingest/schema.py`, the per-signal contract | pandera schema, generic by field name | contract relaxed to three required columns |
| Outliers | robust MAD score on daily changes, threshold 8 | 25% day-over-day percentage | `main`'s, renamed |
| Calendars | per-signal `pandas_market_calendars` | NYSE for every signal | LSE and lag-aware |
| Fama-French | — | fetched, previewed, downloaded | fetched into contract columns |

## The decisions

### One converter, two readers

The Bloomberg CSV reader stays, because the terminal's CSV exports are what
the team actually has and because parsing them well (a metadata block of
varying length, `#N/A N/A` placeholders, one security per file) is real work
that was done properly. It is now `ingest/bloomberg_csv.py` and it produces
the same `BloombergExport` as the workbook reader, so `combine()` in
`ingest/bloomberg.py` joins both kinds through one ticker map into one
contract-shaped frame.

What the CSV branch did not do was produce the contract. Its download, put
through the contract validator as it stood, failed with nine blocking issues:
every column missing, because they were named `SPX_Index_PX_LAST`, and dates
written `02/01/2020`, which the data specification refuses. Mapping the merged
frame onto the contract through the ticker map the workbook converter already
had was the missing step, and the Data page now does it.

The Yahoo/FRED branch is closed with nothing merged. The proposal's boundary
is explicit — "data is ingested via structured CSV upload; no live API
streaming or automated data feeds; confirmed by sponsor" — and each of its
contract changes broke a rule the architecture makes structural: shifting
every column at extraction (§6 rule 1: nothing outside `align_and_lag` shifts
anything), shipping `spx_close_target` columns (the data specification: targets
are derived, never supplied), and demoting six of eight signals to optional.

### One validator

`ingest/schema.py` is the contract; the pandera layer is gone. It classified
columns by field-name substring — `PX_` meant "greater than zero", anything
else meant "between −100 and 10 000" — because the merged frame had no
contract yet, so it could not know that `vix` tops out at 200 or that
`credit_spread_ig` is in percentage points. It also produced a second report
type with no finding ids, no severity and no per-signal grouping, while the
include/exclude review, the pending state and persisted decisions all hang off
`QualityFinding.id` (see [the quality report contract](quality-report-contract.md)).
Two validators are two answers to "is this file usable", and they disagreed.

The architecture does name pandera for `schema.py`. That remains a reasonable
refactor of the *same* contract behind the same `SchemaIssue` interface; it is
not a second contract, and it is not Sprint 1.

One check crossed over: a row dated on a Saturday or Sunday is now a
`weekend_row` warning in the schema check, reported and not blocking.

### One outlier method

The robust MAD score on daily changes at threshold 8 stays; the 25% rule goes.
A percentage rule is a statement about the unit: `spx_close` never moves 25%
in a day, so on SPX it can only ever catch a misplaced decimal, while a credit
spread at 0.6 points moving to 0.8 is a 33% move, routine in a stress week,
and the rule flagged it twice (the move and the reversal). The MAD score is
unit-free, collapses a spike and its rebound onto the offending row, and was
calibrated on the real ten-year pull ([outlier-detection.md](outlier-detection.md)):
282 flags at threshold 4, 44 at 8, every one a real market event. On the tame
synthetic file both methods are quiet (3 flags against 1 over ten years), so
the argument is structural, not a count.

### One calendar approach

Per-signal calendars stay ([market-calendars.md](market-calendars.md)): on the
real data, plain weekdays produced 257 false gaps, NYSE for every signal
produced 18, per-signal calendars produced 1. The 18 are Columbus Day and
Veterans Day every year, when the NYSE trades and the bond market is shut. The
CSV branch's gap labelling used NYSE for everything and would have reproduced
them. The Yahoo/FRED branch's LSE mapping existed only because it proxied the
bond index with a London-listed ETF.

### Fama-French: kept, cached, not in the contract

The parser stays (it finds data rows by their eight-digit date rather than by
fixed offsets). Two things changed. A download is now written under
`data/fama_french/<sha256>.csv` and handed back as a `SourceFile`, because a
live fetch inside a run breaks "same `RunConfig` in, same numbers out" and
because Ken French's library is updated monthly, so the same URL returns
different rows across a sprint. And nothing downloads on its own: the sponsor's
brief is manual data, so a person presses the button.

The factors are inputs to the FF5 benchmark, not signals in the contract. They
enter the signal set only if the sponsor asks for them as predictors, and then
they need release-date dating (§6 rule 3), which the daily file does not carry.

### The app keeps Sprint 1 wired in

The Data page offers two ways in — a signal CSV as it is, or Bloomberg exports
merged on the spot — and both end at the same validation, the same quality
report and the same session key. The front page shows the quality report. The
functional tests that trace the FYP-8, FYP-9, FYP-10 and FYP-25 acceptance
criteria are back, and the Bloomberg page has its own.

## Fixed along the way

- A single blank or unreadable date cell raised `IndexError` from the gap
  check and took the whole quality report with it.
- Calendar construction was repeated sixteen times per report; memoised, the
  ten-year gap check went from about three seconds to about one.
- The upload confirmation quoted a guessed date range for ambiguous dates that
  the validator then refused; it reads ISO only now.
- Bloomberg CSV dates are read with an explicit day/month order settled once
  per file, never inferred cell by cell.
- A repeated date inside one export is kept last and reported, instead of
  crashing the join.
- One functional test embedded 25 MB in its id and overflowed a Windows
  environment-variable limit at teardown.

## Still open

These need the sponsor: the forecast horizon (which fixes the target and the
embargo), the exact Bloomberg securities (exports seen so far include
`LF98TRUU` and `JPMVXYGL`, neither of which is the contract's), the bond index,
whether the Fama-French factors are benchmark regressors only or also
predictors, and the crash definition. The working assumptions in
[the architecture design](superpowers/specs/2026-07-29-forecasting-engine-architecture-design.md)
§11 stand until then.
