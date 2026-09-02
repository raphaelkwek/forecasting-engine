# Market calendars: source, mapping and reconciliation

How the engine decides whether a date missing from an upload is a real gap or a
day the market was shut. Written for auditability: every choice below is
reproducible against the ten years of Bloomberg daily data available on
2026-09-03 — `spx_close`, `agg_close`, `vix`, `credit_spread_ig` and
`breakeven_10y`, 2,610 rows.

## The source

[`pandas_market_calendars`](https://github.com/rsheftel/pandas_market_calendars),
a maintained library of exchange trading calendars. It is a declared dependency
in `pyproject.toml`, so the version in use is pinned in `uv.lock` and recorded in
every report: each gap section's `stats` carries `source`, `version` and the
calendar used per signal.

It was chosen over the alternatives considered:

- **`pandas.tseries.holiday.USFederalHolidayCalendar`**, built into pandas, is
  wrong for this. US *federal* holidays are not exchange holidays: Good Friday
  closes the NYSE and is not federal, while Columbus Day and Veterans Day are
  federal and the NYSE trades through both.
- **`exchange_calendars`** covers exchanges well but has no US bond market
  calendar, which five of the eight signals need.
- **Hard-coded holiday rules** would have to be maintained by hand for as long as
  the project lives, and would still miss ad-hoc closures.

## The mapping

Each signal is reconciled against its own market's calendar. They do not share
one.

| Signal | Calendar | Market |
|---|---|---|
| `spx_close` | `NYSE` | New York Stock Exchange |
| `vix` | `CBOE_Index_Options` | Cboe index options |
| `agg_close` | `SIFMA_US` | US bond market |
| `credit_spread_hy` | `SIFMA_US` | US bond market |
| `credit_spread_ig` | `SIFMA_US` | US bond market |
| `breakeven_10y` | `SIFMA_US` | US bond market |
| `term_spread` | `SIFMA_US` | US bond market |
| `fx_impl_vol` | weekdays | FX trades continuously on weekdays |

A signal with no entry falls back to `SIFMA_US`, the most permissive of the real
calendars, so an unmapped signal errs towards reporting a gap rather than hiding
one.

### Why per-signal, and not one calendar for everything

False gaps produced over the ten-year sample:

| Approach | False gaps |
|---|---|
| Plain weekdays | 257 |
| NYSE for every signal | 18 |
| **Per-signal mapping** | **1** |

The difference is not theoretical. On **Columbus Day** and **Veterans Day** the
NYSE trades while the US bond market is closed. Judging a credit spread by the
equity calendar reports both days as missing data, every year. That single
mismatch accounts for most of the 18.

In the other direction, the bond market trades on days the exchange does not, so
`agg_close` and `breakeven_10y` legitimately carry 87 and 93 observations that
fall outside the NYSE calendar entirely.

## The reconciliation

For each signal, in order:

1. Take the dates where that signal has a value. A blank cell is not data, so a
   row present with an empty cell counts as a gap.
2. Bound the range by that signal's own first and last observation. A file
   covering one week is not missing the rest of the year, and a series that
   starts late is not missing its own pre-history.
3. Ask the calendar which days in that range were sessions.
4. Subtract. What remains are days the market was open and the signal is absent.
5. Group consecutive *sessions* into one finding. A Friday and the following
   Monday are consecutive sessions even though three calendar days separate
   them, so a weekend outage reads as one gap rather than two.

Weekends and holidays never appear, because they are never sessions and so never
enter step 3.

Findings are informational. A gap does not stop the pipeline, consistent with
the severity rules in [the quality report contract](quality-report-contract.md).

## Result on the real data

One flagged gap across five signals over ten years:

```
credit_spread_ig   1 session missing (2018-12-05); SIFMA_US says the market was open
```

## Known limitation: ad-hoc closures

That one flag is a false positive, and it is worth understanding.

**2018-12-05** was the National Day of Mourning for George H. W. Bush. US
markets closed by presidential proclamation rather than by the published
schedule. The `NYSE` and `CBOE_Index_Options` calendars both record the closure;
`SIFMA_US` does not, so a bond-market signal correctly holds no data that day and
the reconciliation reports it as a gap.

Unscheduled closures — days of mourning, weather, systems failures — are exactly
the cases a published schedule cannot anticipate, and calendar libraries record
them unevenly. The check will therefore produce the occasional false gap around
such events. It is a limitation of the calendar data, not of the reconciliation,
and the honest handling is to say so rather than to hard-code exceptions that
would then need maintaining.

Re-check this if `pandas_market_calendars` is upgraded: an improved `SIFMA_US`
calendar would remove this flag.
