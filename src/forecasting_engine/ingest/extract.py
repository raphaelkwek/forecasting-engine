"""Pulling signal data from Yahoo Finance, FRED, and Ken French's Data Library.

This is the automated half of a hybrid extraction pipeline.  Yahoo supplies
market prices (index levels, volatility); FRED supplies economic series
(credit spreads, inflation expectations, yields); Ken French supplies the
Fama-French 5-Factor daily returns.  The Bloomberg Global Aggregate
(``bond_index_global_agg``) is pulled from Yahoo as a proxy (GLBL.L);
``fx_impl_vol`` (G7 FX implied vol) has no free source and is
supplied manually.  VIX is stitched from both Yahoo (^VIX) and FRED (VIXCLS)
so FRED fills any gaps Yahoo leaves.

Every numeric column is shifted forward by one trading day after extraction
(``LAG_ROWS``), so a row dated *t* carries the value observed at *t-1*.
This avoids look-ahead bias: the signal is something a portfolio manager
could have known at the close of the previous day. The two unlagged target
columns (``spx_close_target``, ``bond_index_target``) are the exception:
they keep the value observed at *t*, because the model forecasts the return
between consecutive observed levels, and lagging the observation it is
measured against would distort the target.

Nothing here imports Streamlit; the dashboard is a caller, not a dependency.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from io import BytesIO, StringIO
from pathlib import Path

import fredapi
import pandas as pd
import yfinance as yf
import urllib.request
import zipfile

from forecasting_engine.ingest.provenance import SourceFile
from forecasting_engine.ingest.schema import ALL_COLUMNS, DATE_COLUMN, OUTPUT_DROPPED_COLUMNS, REQUIRED_COLUMNS

log = logging.getLogger(__name__)

# ── Source mappings ──────────────────────────────────────────────────────

#: Yahoo Finance tickers for the market-price signals we can pull.
#:
#: ``bond_index_global_agg`` uses iShares Global Agg (GLBL.L) as a proxy for the Bloomberg
#: Global Aggregate Bond Index.  ``^EVZ`` (euro FX vol) was served by Yahoo for
#: years but stopped updating after 2025-03-06; it is still pulled so historical
#: data is captured, and the staleness detector flags it when it ends before the
#: requested window.  (The yen and pound FX-vol indices, ^JYVIX/^BPVIX, were
#: delisted and are dropped from the pull entirely.)
YAHOO_SERIES: dict[str, str] = {
    "spx_close": "^GSPC",
    "vix": "^VIX",
    "tnx_close": "^TNX",
    "bond_index_global_agg": "GLBL.L",
    "dollar_index": "DX-Y.NYB",
    "eur_fx_vol": "^EVZ",
}

#: Fallback tickers — tried if the primary ticker in YAHOO_SERIES yields no data.
#:
#: Empty on purpose.  AGG was once a fallback for ``bond_index_global_agg``
#: (GLBL.L), but AGG is a *different* security — a US-only index in USD at a
#: ~97 level, vs GLBL.L's global index in GBP at ~18.6.  Filling GLBL.L's gaps
#: with AGG prices injected false ~5x spikes into the column (e.g. 97.07 on
#: 2026-09-01 amid 18.6s), which the outlier detector then had to catch.  A NaN
#: gap is honest; a wrong price is a lie, so there is no fallback.
YAHOO_FALLBACKS: dict[str, str] = {}

#: FRED series IDs for the economic signals we can pull directly.
#:
#: ``credit_spread_ig`` is BAA10Y — Moody's Baa corporate yield minus the
#: 10-year Treasury, a full-history (1986+) investment-grade spread.  (The ICE
#: BofA series BAMLC0A0CM is free only from 2023-09 due to licensing, so it was
#: dropped.)  ``credit_spread_hy`` still uses the ICE high-yield OAS, which FRED
#: only serves from 2023-09; see ``data_sources/bloomberg/credit_spread_hy.csv``
#: for the full-history override.
FRED_SERIES: dict[str, str] = {
    "credit_spread_ig": "BAA10Y",
    "credit_spread_hy": "BAMLH0A0HYM2",
    "breakeven_10y": "T10YIE",
    "breakeven_5y": "T5YIE",
}

#: Ken French Data Library — Fama/French 5 Factors (2x3) daily CSV.
FRENCH_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_5_Factors_2x3_daily_CSV.zip"

#: FRED series used for stitching into an existing column (not placed directly).
_FRED_STITCH: dict[str, str] = {
    "vix": "VIXCLS",
}

#: Columns derived from two FRED legs (long minus short).
FRED_DERIVED: dict[str, tuple[str, str]] = {
    "term_spread": ("DGS10", "DGS2"),
}

#: Columns a person may supply manually to override an automated source.
#: ``bond_index_global_agg`` is auto-sourced from Yahoo (GLBL.L) but may be overridden
#: with the true Bloomberg index; ``fx_impl_vol`` has no free source at all.
MANUAL_COLUMNS: tuple[str, ...] = ("bond_index_global_agg", "fx_impl_vol")

#: Rows of lag.  Each row shows the previous day's value.
LAG_ROWS: int = 1

#: Unlagged observed levels kept out of ``apply_lag``.  A row dated *t* must
#: carry the predictor observed at *t-1* (that is what ``LAG_ROWS`` does) but
#: also the price observed *at* *t*, because the model's target return is
#: ``target[t+1] / target[t] - 1``.  The source columns stay lagged as
#: predictors; exact copies of their pre-lag values are attached after the lag.
UNLAGGED_TARGETS: dict[str, str] = {
    "spx_close": "spx_close_target",
    "bond_index_global_agg": "bond_index_target",
}

#: Where manually exported full-history series live.  A ``<column>.csv`` in this
#: directory (a ``date`` column plus one value column) extends that column by
#: filling the gaps its automated source leaves.  Used for ``credit_spread_hy``:
#: FRED only serves it from 2023-09 onward due to ICE licensing, but a
#: Bloomberg/FactSet export of the high-yield OAS covers it in full.
DATA_SOURCES_DIR: Path = Path("data_sources/bloomberg")

#: Columns that may draw on a full-history CSV in ``DATA_SOURCES_DIR``.
#: ``bond_index_global_agg`` is here because GLBL.L only covers 2018+; a manual
#: Bloomberg export of the true index (LEGATRUU) back-fills 2016-2018.
OVERRIDE_COLUMNS: tuple[str, ...] = ("credit_spread_hy", "bond_index_global_agg")


# ── Extraction report ───────────────────────────────────────────────────

#: A Yahoo series is flagged as stale when more than this share of its values
#: are identical (a frozen/cached feed) or when its data ends more than this
#: many days before the requested end date (a discontinued ticker).
STALE_IDENTICAL_SHARE: float = 0.9
STALE_END_DAYS: int = 30

#: A Yahoo ticker returning fewer rows than this relative to the requested
#: business-day window is suspicious and gets a warning — it may be delisted
#: or serving a handful of legacy rows.
_MIN_ROW_SHARE: float = 0.5


@dataclass
class ExtractionReport:
    """What the extraction did, and what a person still has to supply."""

    rows: int
    start: str | None = None
    end: str | None = None
    yahoo_ok: list[str] = field(default_factory=list)
    yahoo_failed: list[tuple[str, str]] = field(default_factory=list)
    fred_ok: list[str] = field(default_factory=list)
    fred_failed: list[tuple[str, str]] = field(default_factory=list)
    derived: list[str] = field(default_factory=list)
    manual: list[str] = field(default_factory=list)
    #: Column name → why it is suspect (e.g. "data ends 2020-03-13, 300 days
    #: before the requested end; 96% of values are identical").  A stale series
    #: is still placed so downstream columns can use it, but the report flags
    #: it so a person can decide whether the value is trustworthy.
    stale: dict[str, str] = field(default_factory=dict)
    #: Column name → share (0..1) of the requested window that has a value.
    #: Measured against business days, not the series' own index, so a
    #: discontinued ticker shows a low share even though every row it *does*
    #: return is present.
    completeness: dict[str, float] = field(default_factory=dict)

    @property
    def all_ok(self) -> bool:
        return not self.yahoo_failed and not self.fred_failed


#: Columns whose trailing blanks are expected, never a reason to drop a row.
#: ``eur_fx_vol`` is a Yahoo ticker that stopped publishing (~2025-03, kept
#: because it is the only working FX-vol series and its staleness is flagged);
#: the ff_* factors trail the newest month by Ken French's publishing schedule.
#: Rows are kept while every OTHER column has a value; these may trail blank.
CLEAN_EXEMPT_COLUMNS: tuple[str, ...] = (
    "eur_fx_vol",
    "ff_mkt_rf",
    "ff_smb",
    "ff_hml",
    "ff_rmw",
    "ff_cma",
    "ff_rf",
)


@dataclass(frozen=True)
class CleaningSummary:
    """How the final-output trim changed the frame, for the panel to display."""
    rows_before: int
    rows_after: int
    dropped_columns: tuple[str, ...]
    start: str | None
    end: str | None
    exempt_columns: tuple[str, ...] = ()


def clean_output(
    frame: pd.DataFrame,
    *,
    drop_columns: Sequence[str] = OUTPUT_DROPPED_COLUMNS,
    exempt_columns: Sequence[str] = CLEAN_EXEMPT_COLUMNS,
) -> tuple[pd.DataFrame, CleaningSummary]:
    """Trim ``frame`` to the final-output contract: dropped columns gone, no nulls outside ``exempt_columns``.

    Drops ``drop_columns`` (pipeline-internal target twins and discontinued
    series — never in the final CSV), keeps rows where the REQUIRED columns
    (``date``, ``spx_close``, ``vix``) each have a value — every other column,
    including the exempted short feeds and any manually uploaded signal, may
    trail blank (no forward-fill, backfill, or interpolation) — verifies the
    date column has no duplicates (a duplicate would be an extraction bug),
    and sorts ascending by date.  Exempt columns are the known short feeds
    (``eur_fx_vol``, the ff_* factors) whose trailing blanks are expected and
    already flagged as stale elsewhere.  Gap detection is deliberately absent:
    the data-quality report already runs ``gaps.detect`` on whatever frame
    passes through, so this function only guarantees the row set itself.
    """
    if DATE_COLUMN not in frame.columns:
        raise ValueError("final output must carry a date column")

    present = [name for name in drop_columns if name in frame.columns]
    rows_before = len(frame)
    cleaned = frame.drop(columns=present) if present else frame

    n_duplicates = int(cleaned[DATE_COLUMN].duplicated().sum())
    if n_duplicates:
        raise ValueError(
            f"final output has {n_duplicates} duplicate dates — each date must appear exactly once"
        )

    exempt_present = [name for name in exempt_columns if name in cleaned.columns]
    # Only REQUIRED columns (date, spx_close, vix) must have values.  Every
    # other column — the exempted short feeds AND any manual upload — may trail
    # NaN; a manual file can even extend the date range beyond the API window.
    required_present = [c for c in REQUIRED_COLUMNS if c in cleaned.columns]
    if required_present:
        cleaned = cleaned.dropna(subset=required_present)
    cleaned = cleaned.sort_values(DATE_COLUMN, ignore_index=True)

    start = str(cleaned[DATE_COLUMN].iloc[0])[:10] if not cleaned.empty else None
    end = str(cleaned[DATE_COLUMN].iloc[-1])[:10] if not cleaned.empty else None
    summary = CleaningSummary(
        rows_before=rows_before,
        rows_after=len(cleaned),
        dropped_columns=tuple(present),
        start=start,
        end=end,
        exempt_columns=tuple(exempt_present),
    )
    return cleaned, summary


# ── Yahoo Finance ───────────────────────────────────────────────────────

def extract_yahoo(
    start: date, end: date
) -> tuple[dict[str, pd.Series], list[str], list[tuple[str, str]]]:
    """Fetch market-price series from Yahoo Finance.

    Returns ``(placed, ok, failed)`` where *placed* maps contract column
    names to Series indexed by ISO date strings.

    If a primary ticker yields no data and a fallback exists in
    ``YAHOO_FALLBACKS``, the fallback ticker is tried automatically.
    """
    placed: dict[str, pd.Series] = {}
    ok: list[str] = []
    failed: list[tuple[str, str]] = []

    # Collect all tickers to download (primary + fallbacks).
    all_tickers = list(YAHOO_SERIES.values()) + [
        t for t in YAHOO_FALLBACKS.values() if t not in YAHOO_SERIES.values()
    ]
    if not all_tickers:
        return placed, ok, failed

    try:
        raw = yf.download(all_tickers, start=start, end=end, progress=False, auto_adjust=True)
    except Exception as exc:
        failed.append(("yahoo", f"download failed: {exc}"))
        return placed, ok, failed

    if raw.empty:
        failed.append(("yahoo", "returned an empty frame"))
        return placed, ok, failed

    for column, ticker in YAHOO_SERIES.items():
        try:
            if len(all_tickers) == 1:
                close = raw["Close"]
            else:
                close = raw["Close"][ticker]
            n = 0 if close is None else int(pd.to_numeric(close, errors="coerce").notna().sum())
            log.info("Yahoo %s (%s) returned %d non-null rows before merge", column, ticker, n)
            # Targeted diagnostics: euro FX vol is a known-stale ticker, and
            # bond_index_global_agg (GLBL.L) is the bond forecasting target — its coverage
            # is what we're asked to confirm, so it is called out explicitly.
            if column == "bond_index_global_agg":
                log.warning(
                    "[BOND DIAG] %s (%s): %d rows returned — the bond index proxy",
                    column, ticker, n,
                )
            elif column == "eur_fx_vol":
                log.warning(
                    "[FX VOL DIAG] %s (%s): %d rows returned — may be stale (stopped updating ~2025-03)",
                    column, ticker, n,
                )
            series = _to_iso_series(close)
            if series is not None:
                placed[column] = series
                ok.append(column)
                _warn_if_sparse(series, column, ticker, start, end)
            elif column in YAHOO_FALLBACKS:
                # Try the fallback ticker.
                fb_ticker = YAHOO_FALLBACKS[column]
                try:
                    fb_close = raw["Close"][fb_ticker]
                    fb_series = _to_iso_series(fb_close)
                    if fb_series is not None:
                        placed[column] = fb_series
                        ok.append(column)
                        _warn_if_sparse(fb_series, column, fb_ticker, start, end)
                    else:
                        failed.append((column, "no usable values from primary or fallback"))
                except Exception:
                    failed.append((column, "no usable values from primary or fallback"))
            else:
                failed.append((column, "no usable values"))
        except Exception as exc:
            failed.append((column, str(exc)))

    # Where a column has a fallback ticker and the primary came back partial
    # (e.g. GLBL.L starts 2018 but AGG goes back to 2016), fill the primary's
    # gaps from the fallback so the column gets as much history as Yahoo has.
    for column, fb_ticker in YAHOO_FALLBACKS.items():
        if column not in placed or fb_ticker not in raw["Close"].columns:
            continue
        fb_series = _to_iso_series(raw["Close"][fb_ticker])
        if fb_series is None:
            continue
        # Only extend when the fallback actually reaches further back (or
        # covers dates the primary lacks); otherwise it is just a no-op join.
        before = len(placed[column])
        filled = placed[column].combine_first(fb_series)
        if len(filled) > before:
            placed[column] = filled
            log.info("extended %s from fallback %s (%d extra rows)", column, fb_ticker,
                     len(filled) - before)

    return placed, ok, failed


def _warn_if_sparse(
    series: pd.Series, column: str, ticker: str, start: date, end: date
) -> None:
    """Log a warning when a ticker returns far fewer rows than the window expects.

    A delisted ticker (e.g. ^JYVIX/^BPVIX) comes back with a handful of legacy
    rows rather than none at all.  Without this guard the near-empty column
    would be merged in silently and look like missing data downstream.
    """
    window = pd.bdate_range(start=start, end=end)
    if len(window) == 0:
        return
    share = len(series) / len(window)
    if share < _MIN_ROW_SHARE:
        log.warning(
            "%s (%s): only %.0f%% of the requested window has data "
            "(%d of %d business days); the ticker may be delisted or sparse.",
            column, ticker, share * 100, len(series), len(window),
        )


# ── FRED ────────────────────────────────────────────────────────────────

def extract_fred(
    api_key: str, start: date, end: date
) -> tuple[dict[str, pd.Series], list[str], list[tuple[str, str]], dict[str, pd.Series]]:
    """Fetch economic series from FRED.

    Returns ``(placed, ok, failed, stitch)`` where *stitch* holds series
    meant to be merged into an existing column (e.g. VIXCLS into vix).
    """
    placed: dict[str, pd.Series] = {}
    ok: list[str] = []
    failed: list[tuple[str, str]] = []
    stitch: dict[str, pd.Series] = {}

    try:
        fred = fredapi.Fred(api_key=api_key)
    except Exception as exc:
        failed.append(("fred", f"client init failed: {exc}"))
        return placed, ok, failed, stitch

    all_series: dict[str, pd.Series] = {}

    # Defensive check: the FRED series we pull (credit spreads, breakevens)
    # go back decades, so a caller asking for only a few months is almost
    # always a mistake, not a choice.  Refuse nothing (the caller may have a
    # good reason), but say so loudly instead of silently handing back a short
    # history.  ``start`` and ``end`` are passed straight to
    # ``fred.get_series(..., observation_start=start, observation_end=end)``,
    # which is what bounds the returned window; this guard exists to catch an
    # upstream caller feeding the wrong dates before the API round-trips.
    if end - start < timedelta(days=365):
        log.warning(
            "FRED extraction requested a %.0f-day window (%s to %s) for series "
            "that have decades of history; the returned columns will be short.",
            (end - start).days, start, end,
        )

    log.info(
        "FRED observation_start=%s observation_end=%s (ISO dates sent verbatim to the API)",
        start.isoformat(), end.isoformat(),
    )
    for column, series_id in {**FRED_SERIES, **_FRED_STITCH}.items():
        try:
            log.info("FRED fetching %s (%s) observation_start=%s", column, series_id, start.isoformat())
            raw = fred.get_series(series_id, observation_start=start, observation_end=end)
            n = 0 if raw is None else int(raw.notna().sum())
            log.info("FRED %s (%s) returned %d non-null rows", column, series_id, n)
            series = _to_iso_series(raw)
            if series is not None:
                all_series[series_id] = series
                # Direct series go into placed; stitch series are handled later.
                if column in FRED_SERIES:
                    placed[column] = series
                    ok.append(column)
                    _warn_if_short_history(series, column, series_id, start)
                else:
                    stitch[column] = series
                    ok.append(f"{column} (stitch)")
                    _warn_if_short_history(series, column, series_id, start)
            else:
                failed.append((column, "no usable values"))
        except Exception as exc:
            failed.append((column, f"{series_id}: {exc}"))

    # Fetch legs for derived columns.
    leg_ids = {leg for legs in FRED_DERIVED.values() for leg in legs}
    for leg_id in leg_ids:
        if leg_id in all_series:
            continue
        try:
            raw = fred.get_series(leg_id, observation_start=start, observation_end=end)
            series = _to_iso_series(raw)
            if series is not None:
                all_series[leg_id] = series
        except Exception:
            pass  # derivation will fail gracefully below

    for column, (long_leg, short_leg) in FRED_DERIVED.items():
        if long_leg in all_series and short_leg in all_series:
            placed[column] = all_series[long_leg] - all_series[short_leg]
            ok.append(column)
        elif long_leg in all_series or short_leg in all_series:
            absent = short_leg if long_leg in all_series else long_leg
            failed.append((column, f"needs {long_leg} and {short_leg}; {absent} missing"))

    return placed, ok, failed, stitch


# ── Fama-French (Ken French Data Library) ─────────────────────────────

#: Column mapping from Ken French's CSV headers to our schema names.
_FRENCH_COLUMNS: dict[str, str] = {
    "Mkt-RF": "ff_mkt_rf",
    "SMB": "ff_smb",
    "HML": "ff_hml",
    "RMW": "ff_rmw",
    "CMA": "ff_cma",
    "RF": "ff_rf",
}


def extract_french(
    start: date, end: date
) -> tuple[dict[str, pd.Series], list[str], list[tuple[str, str]]]:
    """Fetch Fama-French 5-Factor daily data from Ken French's Data Library.

    Returns ``(placed, ok, failed)`` where *placed* maps contract column
    names to Series indexed by ISO date strings.
    """
    placed: dict[str, pd.Series] = {}
    ok: list[str] = []
    failed: list[tuple[str, str]] = []

    try:
        log.info("Ken French: fetching Fama-French 5 Factors daily from %s", FRENCH_URL)
        resp = urllib.request.urlopen(FRENCH_URL, timeout=30)
        raw_bytes = resp.read()
    except Exception as exc:
        failed.append(("french", f"download failed: {exc}"))
        return placed, ok, failed

    # The response may be a zip archive or a raw text/CSV.
    try:
        if raw_bytes[:2] == b"PK":
            with zipfile.ZipFile(BytesIO(raw_bytes)) as zf:
                csv_name = next(n for n in zf.namelist() if n.endswith(".csv"))
                text = zf.read(csv_name).decode("utf-8")
        else:
            text = raw_bytes.decode("utf-8")
    except Exception as exc:
        failed.append(("french", f"could not read response: {exc}"))
        return placed, ok, failed

    # Ken French files have a title line, then a blank line, then the CSV,
    # then a trailing copyright line.  We find the first data row (the first
    # line whose leading field is a plain date like YYYYMMDD), then the header
    # row is the one directly above it.  The header's date column is empty
    # (",Mkt-RF,SMB,..."), so it carries no digits and can't be spotted by the
    # data-detection heuristic itself.
    lines = text.strip().splitlines()
    data_start = 0
    for i, line in enumerate(lines):
        first_field = line.split(",")[0].strip()
        if first_field.isdigit():
            data_start = i
            break

    # Trim trailing non-data lines (e.g. copyright notices).
    data_lines = lines[data_start:]
    while data_lines and not data_lines[-1].split(",")[0].strip().isdigit():
        data_lines.pop()

    header_start = max(data_start - 1, 0)
    block = lines[header_start : data_start + len(data_lines)]

    try:
        df = pd.read_csv(
            StringIO("\n".join(block)),
            skipinitialspace=True,
        )
    except Exception as exc:
        failed.append(("french", f"CSV parse failed: {exc}"))
        return placed, ok, failed

    # Normalise the date column name (Ken French uses "Date" or "date").
    date_col = df.columns[0]
    df[date_col] = pd.to_datetime(df[date_col], format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=[date_col])
    df["date"] = df[date_col].dt.strftime("%Y-%m-%d")
    df = df.set_index("date")

    # The full Ken French file covers 1963-present.  Trim to the caller's
    # requested window so we don't inject thousands of pre-2016 rows where
    # every other signal is NaN.
    df = df.loc[start.isoformat() : end.isoformat()]

    n_rows = len(df)
    log.info("Ken French: parsed %d rows (%s to %s)", n_rows, df.index.min(), df.index.max())

    for ff_col, schema_col in _FRENCH_COLUMNS.items():
        if ff_col not in df.columns:
            log.warning("Ken French: column %s not found in CSV", ff_col)
            failed.append((schema_col, f"column {ff_col} not in CSV"))
            continue
        series = pd.to_numeric(df[ff_col], errors="coerce")
        series.index.name = DATE_COLUMN
        placed[schema_col] = series
        ok.append(schema_col)

    return placed, ok, failed


# ── Lag ─────────────────────────────────────────────────────────────────

def apply_lag(frame: pd.DataFrame) -> pd.DataFrame:
    """Shift every numeric column down by ``LAG_ROWS``.

    The first ``LAG_ROWS`` rows become NaN for numeric columns.  The date
    column is untouched — it still names the row, not the observation.
    """
    if LAG_ROWS <= 0:
        return frame

    adjusted = frame.copy()
    numeric = [c for c in adjusted.columns if c != DATE_COLUMN]
    adjusted[numeric] = adjusted[numeric].shift(LAG_ROWS)
    return adjusted


# ── Orchestration ───────────────────────────────────────────────────────

def extract_all(
    api_key: str, start: date, end: date
) -> tuple[pd.DataFrame, ExtractionReport]:
    """Run every available extraction and assemble the contract-shaped frame.

    Reuses ``bloomberg._assemble`` for column ordering and date joining.
    """
    from forecasting_engine.ingest.bloomberg import _assemble

    placed: dict[str, pd.Series] = {}
    report = ExtractionReport(rows=0)

    # Yahoo
    y_placed, y_ok, y_failed = extract_yahoo(start, end)
    placed.update(y_placed)
    report.yahoo_ok = y_ok
    report.yahoo_failed = y_failed

    # FRED
    f_placed, f_ok, f_failed, f_stitch = extract_fred(api_key, start, end)
    placed.update(f_placed)
    report.fred_ok = f_ok
    report.fred_failed = f_failed

    # Fama-French
    ff_placed, ff_ok, ff_failed = extract_french(start, end)
    placed.update(ff_placed)
    report.fred_ok.extend(ff_ok)   # group under the same report bucket
    report.fred_failed.extend(ff_failed)

    # Stitch: FRED series (e.g. VIXCLS) fill gaps in the same-named column.
    for column, stitch_series in f_stitch.items():
        if column in placed:
            placed[column] = placed[column].combine_first(stitch_series)
        else:
            placed[column] = stitch_series
            report.fred_ok.append(f"{column} (stitch)")

    # Derived columns already placed by extract_fred.
    report.derived = [c for c in FRED_DERIVED if c in placed]
    report.manual = list(MANUAL_COLUMNS)

    # Full-history overrides: a CSV in DATA_SOURCES_DIR extends a column whose
    # free source is restricted (e.g. credit_spread_hy, FRED serves only 2023+).
    for column in OVERRIDE_COLUMNS:
        _apply_override(placed, report, column, DATA_SOURCES_DIR / f"{column}.csv")

    # Per-series completeness and staleness, measured against the requested
    # window.  Requires ``end`` (Yahoo gives us nothing beyond it, so a
    # delisted ticker naturally shows up as incomplete/stale here).
    report.completeness = {
        col: _completeness(series, start, end) for col, series in placed.items()
    }
    for col, series in placed.items():
        reason = _staleness_reason(series, end)
        if reason:
            report.stale[col] = reason

    frame = _assemble(placed)

    # Capture the unlagged observed levels before ``apply_lag`` shifts every
    # predictor down by one row, then re-attach them after the shift.  The
    # targets are the raw values at date *t* the model forecasts the return of;
    # they must never be lagged themselves.
    observed = frame[[c for c in UNLAGGED_TARGETS if c in frame.columns]].copy()

    frame = apply_lag(frame)

    for source, target in UNLAGGED_TARGETS.items():
        if source in observed.columns:
            frame[target] = observed[source].to_numpy()
            report.completeness[target] = report.completeness.get(source, 0.0)

    # Contract column order (``_assemble`` cannot place the targets because
    # they only exist after the lag).
    frame = frame.reindex(columns=[c for c in ALL_COLUMNS if c in frame.columns])

    dates = pd.to_datetime(frame[DATE_COLUMN], errors="coerce", format="ISO8601").dropna()
    if not dates.empty:
        report.start = dates.min().date().isoformat()
        report.end = dates.max().date().isoformat()
    report.rows = len(frame)

    return frame, report


def to_accepted(
    frame: pd.DataFrame, report: ExtractionReport
) -> SourceFile:
    """Wrap the extracted frame as a ``SourceFile`` for the validation pipeline.

    The frame is serialised to CSV bytes so ``SourceFile.of`` can compute
    the content hash.  No bytes are written to disk.
    """
    csv_bytes = frame.to_csv(index=False).encode("utf-8")
    name = f"extracted_{report.start}_to_{report.end}.csv"
    return SourceFile.of(name, csv_bytes)


# ── Manual supplement ───────────────────────────────────────────────────

def merge_manual_columns(
    frame: pd.DataFrame, column: str, csv_bytes: bytes
) -> pd.DataFrame:
    """Merge one manually supplied column into the extracted frame by date.

    The CSV must have a date column (named case-insensitively
    ``Date``/``Dates``/``date``, or a first column that mostly parses as dates)
    and one value column (the first non-date column that parses as numeric —
    ``PX_LAST`` in a Bloomberg export).  Rows are aligned on the date with an
    outer join, so a manual series that reaches beyond the extracted window
    extends it (a fresh column's dates are its own).  Missing dates stay NaN.
    The lag is not re-applied: the extractor already lagged the automated
    columns, and manual values are assumed to be provided at the same lag
    convention.
    """
    try:
        raw = pd.read_csv(BytesIO(csv_bytes), encoding="utf-8-sig")
    except Exception as exc:
        raise ValueError(f"{column}: unreadable CSV: {exc}") from exc

    date_col, value_col = _resolve_manual_columns(raw, column)

    # Normalise both sides to ISO date strings so the join aligns.
    manual = raw[[date_col, value_col]].copy()
    manual[DATE_COLUMN] = pd.to_datetime(manual[date_col], errors="coerce").dt.strftime(
        "%Y-%m-%d"
    )
    manual[column] = pd.to_numeric(manual[value_col], errors="coerce")
    # A daily export can repeat a date (intraday timestamps); keep one row per
    # date so the outer join stays 1:1 and clean_output's guard stays a safety
    # net rather than a complaint about the manual file.
    manual = _collapse_daily_rows(manual, column)

    merged = frame.copy()
    if column in merged.columns:
        merged = merged.drop(columns=[column])
    merged[DATE_COLUMN] = pd.to_datetime(merged[DATE_COLUMN], errors="coerce").dt.strftime(
        "%Y-%m-%d"
    )

    # Outer join: the manual file's dates are included even where the extracted
    # window has none (a fresh signal's coverage is its own).  The existing
    # ``column`` was dropped above, so on overlapping dates the manual value is
    # the only one present — the manual source wins.
    out = merged.merge(manual[[DATE_COLUMN, column]], on=DATE_COLUMN, how="outer")
    return out.sort_values(DATE_COLUMN).reset_index(drop=True)


# ── Helpers ─────────────────────────────────────────────────────────────

#: Case-insensitive date-column names a manual CSV may use.  ``Dates`` is the
#: default Bloomberg history-export header; ``Date``/``date`` the engine's own
#: contract; the rest are common exports.
_DATE_NAMES: tuple[str, ...] = ("date", "dates", "dt", "trade date", "trade_date")


def _collapse_daily_rows(table: pd.DataFrame, column: str) -> pd.DataFrame:
    """Keep one row per date in a normalized (date, value) manual table.

    A daily export can legitimately carry several rows for one date — intraday
    timestamps, or the same observation re-emitted — so the later merge stays
    1:1 per date.  The last row per date wins; rows whose date failed to parse
    are dropped here rather than drifting in as blank dates.  This is what keeps
    ``clean_output``'s duplicate-date guard from firing on manual files.
    """
    clean = table.dropna(subset=[DATE_COLUMN])
    repeats = len(clean) - int(clean[DATE_COLUMN].nunique())
    if repeats:
        log.warning(
            "collapsed %d repeat row(s) to one per date in %s", repeats, column
        )
    return (
        clean.sort_values(DATE_COLUMN)
        .drop_duplicates(subset=[DATE_COLUMN], keep="last")
        .reset_index(drop=True)
    )


def _resolve_manual_columns(raw: pd.DataFrame, column: str) -> tuple[str, str]:
    """Pick the date and value columns of a manual CSV without requiring names.

    Date column: the first column whose name lowercases to one of
    ``_DATE_NAMES`` (so ``Date``, ``Dates``, ``trade date`` all work); failing
    that, the first column when at least 80% of its non-null values parse as
    dates (covers a Bloomberg export whose date header is e.g. ``Interval``).
    Value column: the first *other* column whose non-null values are mostly
    numeric (``PX_LAST`` in an export).

    ``column`` names the signal in error messages.  A CSV that matches neither
    raises a ``ValueError`` the manual-upload UI surfaces verbatim.
    """
    lower = {c: str(c).strip().lower() for c in raw.columns}

    date_col = next((c for c in raw.columns if lower[c] in _DATE_NAMES), None)
    if date_col is None and len(raw.columns):
        first = raw.columns[0]
        if _parses_as_dates(raw[first]):
            date_col = first

    if date_col is None:
        raise ValueError(
            f"{column}: no date column found in CSV (columns: {list(raw.columns)}). "
            "Expect a 'Date'/'Dates'/'date' column and one value column, e.g. PX_LAST."
        )

    value_col = next(
        (c for c in raw.columns if c != date_col and _parses_as_numeric(raw[c])),
        None,
    )
    if value_col is None:
        raise ValueError(
            f"{column}: no value column found in CSV (columns: {list(raw.columns)}). "
            "Expect a date column and one numeric value column, e.g. PX_LAST."
        )
    return date_col, value_col


def _parses_as_dates(s: pd.Series) -> bool:
    """True when at least 80% of a column's non-null cells parse as dates."""
    present = s.notna()
    if not present.any():
        return False
    return float(pd.to_datetime(s, errors="coerce").notna()[present].mean()) >= 0.8


def _parses_as_numeric(s: pd.Series) -> bool:
    """True when at least 80% of a column's non-null cells parse as numbers."""
    present = s.notna()
    if not present.any():
        return False
    return float(pd.to_numeric(s, errors="coerce").notna()[present].mean()) >= 0.8


def _apply_override(
    placed: dict[str, pd.Series], report: ExtractionReport, column: str, path: Path
) -> None:
    """Override ``column`` from a full-history CSV in ``DATA_SOURCES_DIR``, if present.

    The CSV carries a date column (recognised case-insensitively — ``Date``,
    ``Dates``, ``date`` — or a first column that parses as dates) and one value
    column.  The export's values REPLACE the automated source where the two
    overlap — a manual export is authoritative, the whole point of supplying it —
    and the automated source only fills dates the export leaves blank, so the
    column picks up the export's full history.  A missing, unreadable, or
    malformed file is skipped, not an error — the override is optional by design.
    """
    if not path.is_file():
        return
    try:
        raw = pd.read_csv(path, encoding="utf-8-sig")
    except Exception as exc:
        log.warning("could not read override %s for %s: %s", path, column, exc)
        return

    try:
        date_col, value_col = _resolve_manual_columns(raw, column)
    except ValueError as exc:
        log.warning("override %s for %s: %s", path, column, exc)
        return

    override = raw[[date_col, value_col]].copy()
    override[DATE_COLUMN] = pd.to_datetime(override[date_col], errors="coerce").dt.strftime(
        "%Y-%m-%d"
    )
    override[column] = pd.to_numeric(override[value_col], errors="coerce").dropna()
    override = override.dropna(subset=[column])
    override = _collapse_daily_rows(override, column)
    override = override.set_index(DATE_COLUMN)[column]

    if override.empty:
        log.warning("override %s for %s is empty", path, column)
        return

    before = len(placed[column]) if column in placed else 0
    # The manual export wins on overlap: override.combine_first(placed) keeps
    # the override's value wherever it exists and falls back to the automated
    # source only on dates the export cannot cover.  (The old operand order,
    # placed.combine_first(override), filled gaps only — it kept the Yahoo
    # scale on overlap and spliced two incompatible series together.)
    placed[column] = override.combine_first(placed[column]) if column in placed else override
    log.info(
        "extended %s from override %s (%d -> %d rows)",
        column, path, before, len(placed[column]),
    )
    report.derived.append(f"{column} (override)")


def _to_iso_series(raw: pd.Series) -> pd.Series | None:
    """Normalise a pandas Series to one indexed by ISO date strings."""
    if raw is None or raw.empty:
        return None

    s = raw.dropna()
    if s.empty:
        return None

    # Normalise the index to date objects, then to ISO strings.
    idx = pd.to_datetime(s.index).date
    s = pd.Series(s.values, index=pd.Index([d.isoformat() for d in idx], name=DATE_COLUMN))
    s = s.sort_index()
    return s



def _warn_if_short_history(
    series: pd.Series, column: str, series_id: str, start: date
) -> None:
    """Log a warning when a FRED series starts well after the requested window.

    The FRED series we pull (credit spreads, breakevens) go back decades.  If
    the API returns a series that begins months after ``start``, either the
    caller passed the wrong dates or the API truncated the range — neither
    should be silent.
    """
    first = pd.to_datetime(series.index, errors="coerce").dropna()
    if not len(first) or start is None:
        return
    lag = (first.min() - pd.Timestamp(start)).days
    if lag > 30:
        log.warning(
            "%s (%s): starts %s, %d days after the requested start %s; "
            "the series may have been truncated.",
            column, series_id, first.min().date().isoformat(), lag, start,
        )


def _completeness(series: pd.Series, start: date, end: date) -> float:
    """Share (0..1) of the requested business-day window covered by ``series``.

    Measured against business days so the denominator is stable regardless of
    what calendar the source keeps.  Values only count on dates inside the
    requested window.
    """
    if series is None or len(series) == 0:
        return 0.0
    window = pd.bdate_range(start=start, end=end)
    if len(window) == 0:
        return 0.0
    idx = pd.to_datetime(series.index, errors="coerce")
    in_window = (idx >= pd.Timestamp(start)) & (idx <= pd.Timestamp(end))
    return float(in_window.sum()) / float(len(window))


def _staleness_reason(series: pd.Series, end: date) -> str | None:
    """Return a human reason if ``series`` looks stale, else None.

    Two heuristics cover the Yahoo FX-vol failures:
      * A discontinued ticker returns no data at all — handled upstream as a
        plain failure, so a wholly missing series never reaches here.
      * A stale/cached feed repeats the same value across most dates, or ends
        well before the requested end date even though data existed.  Either
        way the series carries little signal and a person should know.
    """
    if series is None or len(series) == 0:
        return None

    parts: list[str] = []

    values = pd.to_numeric(series, errors="coerce").dropna()
    if len(values) >= 2:
        identical = float((values == values.iloc[0]).mean())
        if identical >= STALE_IDENTICAL_SHARE:
            parts.append(f"{identical:.0%} of values are identical")

    dates = pd.to_datetime(series.index, errors="coerce").dropna()
    if len(dates) and end is not None:
        last = dates.max()
        gap = (pd.Timestamp(end) - last).days
        if gap > STALE_END_DAYS:
            parts.append(
                f"data ends {last.date().isoformat()}, {gap} days before the requested end"
            )

    if not parts:
        return None
    return "; ".join(parts)
