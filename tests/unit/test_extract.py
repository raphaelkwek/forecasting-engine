"""Unit tests for the automated extraction module.

All API calls are mocked — no network traffic in tests.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from forecasting_engine.ingest.extract import (
    MANUAL_COLUMNS,
    YAHOO_SERIES,
    ExtractionReport,
    _apply_override,
    _completeness,
    _staleness_reason,
    _to_iso_series,
    apply_lag,
    extract_all,
    extract_fred,
    extract_french,
    extract_yahoo,
    merge_manual_columns,
    to_accepted,
)
from forecasting_engine.ingest.schema import ALL_COLUMNS, DATE_COLUMN

# ── Helpers ─────────────────────────────────────────────────────────────

def _make_yahoo_frame(tickers: list[str], dates: list[str]) -> pd.DataFrame:
    """Build a DataFrame matching yfinance.download() output shape."""
    rng = np.random.default_rng(0)
    data = {}
    for ticker in tickers:
        data[("Close", ticker)] = rng.uniform(100, 5000, len(dates))
    return pd.DataFrame(data, index=pd.DatetimeIndex(dates))


def _make_fred_series(dates: list[str], start_val: float = 1.0) -> pd.Series:
    """Build a Series matching fredapi.get_series() output shape."""
    vals = np.linspace(start_val, start_val + 1, len(dates))
    return pd.Series(vals, index=pd.DatetimeIndex(dates))


# ── _to_iso_series ──────────────────────────────────────────────────────

class TestToIsoSeries:
    def test_normalisesDatetimeIndex(self):
        dates = ["2025-01-02", "2025-01-03"]
        raw = pd.Series([1.0, 2.0], index=pd.DatetimeIndex(dates))
        result = _to_iso_series(raw)
        assert result is not None
        assert list(result.index) == dates

    def test_drops_na(self):
        dates = ["2025-01-02", "2025-01-03", "2025-01-04"]
        raw = pd.Series([1.0, np.nan, 3.0], index=pd.DatetimeIndex(dates))
        result = _to_iso_series(raw)
        assert result is not None
        assert len(result) == 2

    def test_returns_none_for_empty(self):
        assert _to_iso_series(pd.Series(dtype=float)) is None
        assert _to_iso_series(None) is None  # type: ignore[arg-type]

    def test_sorts_ascending(self):
        dates = ["2025-01-04", "2025-01-02", "2025-01-03"]
        raw = pd.Series([3.0, 1.0, 2.0], index=pd.DatetimeIndex(dates))
        result = _to_iso_series(raw)
        assert list(result.index) == ["2025-01-02", "2025-01-03", "2025-01-04"]


# ── extract_yahoo ───────────────────────────────────────────────────────

class TestExtractYahoo:
    @patch("forecasting_engine.ingest.extract.yf")
    def test_returns_series_per_ticker(self, mock_yf):
        dates = ["2025-01-02", "2025-01-03", "2025-01-06"]
        mock_yf.download.return_value = _make_yahoo_frame(
            list(YAHOO_SERIES.values()), dates
        )
        placed, ok, failed = extract_yahoo(date(2025, 1, 1), date(2025, 1, 10))

        assert set(placed) == set(YAHOO_SERIES)
        assert len(ok) == len(YAHOO_SERIES)
        assert failed == []

    @patch("forecasting_engine.ingest.extract.yf")
    def test_handles_download_failure(self, mock_yf):
        mock_yf.download.side_effect = RuntimeError("network error")
        placed, ok, failed = extract_yahoo(date(2025, 1, 1), date(2025, 1, 10))

        assert placed == {}
        assert len(failed) == 1
        assert "yahoo" in failed[0][0]

    @patch("forecasting_engine.ingest.extract.yf")
    def test_handles_empty_response(self, mock_yf):
        mock_yf.download.return_value = pd.DataFrame()
        placed, ok, failed = extract_yahoo(date(2025, 1, 1), date(2025, 1, 10))

        assert placed == {}
        assert len(failed) == 1


# ── extract_fred ────────────────────────────────────────────────────────

class TestExtractFRED:
    @patch("forecasting_engine.ingest.extract.fredapi.Fred")
    def test_returns_series_per_column(self, mock_fred_cls):
        dates = ["2025-01-02", "2025-01-03", "2025-01-06"]
        instance = mock_fred_cls.return_value
        instance.get_series.side_effect = lambda sid, **kw: _make_fred_series(dates)

        placed, ok, failed, stitch = extract_fred(
            "test-key", date(2025, 1, 1), date(2025, 1, 10)
        )

        # Direct columns + derived
        assert "credit_spread_ig" in placed
        assert "credit_spread_hy" in placed
        assert "breakeven_10y" in placed
        assert "breakeven_5y" in placed
        assert "term_spread" in placed
        assert "vix" in stitch
        assert failed == []

    @patch("forecasting_engine.ingest.extract.fredapi.Fred")
    def test_derived_needs_both_legs(self, mock_fred_cls):
        dates = ["2025-01-02"]
        instance = mock_fred_cls.return_value

        def side_effect(sid, **kw):
            if sid == "DGS2":
                raise RuntimeError("series not found")
            return _make_fred_series(dates)

        instance.get_series.side_effect = side_effect
        placed, ok, failed, stitch = extract_fred(
            "test-key", date(2025, 1, 1), date(2025, 1, 10)
        )

        assert "term_spread" not in placed
        assert any("term_spread" in f[0] for f in failed)


# ── extract_french ──────────────────────────────────────────────────────

FRENCH_ZIP = (
    b"PK\x03\x04" + b"\x00" * 8
)  # placeholder; replaced by real zip in the fixture below


def _french_zip_bytes() -> bytes:
    """A real zip containing a Ken French-style 5-factor CSV."""
    import io
    import zipfile

    csv_text = (
        "F-F_Research_Data_5_Factors_2x3_daily\n"
        "This file was created using the following data...\n"
        "  Kenneth R. French\n"
        "\n"
        ",Mkt-RF,SMB,HML,RMW,CMA,RF\n"
        "20240102,   0.05,   0.02,   0.01,   0.02,   0.01,   0.01\n"
        "20240103,   0.06,  -0.01,   0.02,   0.01,   0.00,   0.01\n"
        "20240104,  -0.03,   0.04,   0.00,  -0.01,   0.02,   0.01\n"
        "\n"
        "Copyright 2024 Eugene F. Fama and Kenneth R. French\n"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("F-F_Research_Data_5_Factors_2x3_daily.csv", csv_text)
    return buf.getvalue()


class TestExtractFrench:
    def test_returns_all_five_factors_plus_rf(self):
        with patch(
            "forecasting_engine.ingest.extract.urllib.request.urlopen"
        ) as mock_open:
            mock_open.return_value.read.return_value = _french_zip_bytes()
            placed, ok, failed = extract_french(date(2024, 1, 1), date(2024, 1, 10))

        assert set(placed) == {
            "ff_mkt_rf", "ff_smb", "ff_hml", "ff_rmw", "ff_cma", "ff_rf",
        }
        assert len(ok) == 6
        assert failed == []
        assert list(placed["ff_mkt_rf"].index) == ["2024-01-02", "2024-01-03", "2024-01-04"]

    def test_values_are_parsed_as_percent(self):
        with patch(
            "forecasting_engine.ingest.extract.urllib.request.urlopen"
        ) as mock_open:
            mock_open.return_value.read.return_value = _french_zip_bytes()
            placed, _, _ = extract_french(date(2024, 1, 1), date(2024, 1, 10))

        assert placed["ff_mkt_rf"].iloc[0] == 0.05
        assert placed["ff_smb"].iloc[1] == -0.01

    def test_download_failure_is_reported(self):
        with patch(
            "forecasting_engine.ingest.extract.urllib.request.urlopen"
        ) as mock_open:
            mock_open.side_effect = RuntimeError("network error")
            placed, ok, failed = extract_french(date(2024, 1, 1), date(2024, 1, 10))

        assert placed == {}
        assert ok == []
        assert "french" in failed[0][0]


# ── apply_lag ───────────────────────────────────────────────────────────

class TestApplyLag:
    def test_shifts_numeric_by_one(self):
        frame = pd.DataFrame(
            {DATE_COLUMN: ["2025-01-02", "2025-01-03", "2025-01-06"],
             "spx_close": [100.0, 200.0, 300.0],
             "vix": [15.0, 16.0, 17.0]}
        )
        result = apply_lag(frame)

        assert result[DATE_COLUMN].tolist() == frame[DATE_COLUMN].tolist()
        assert pd.isna(result["spx_close"].iloc[0])
        assert result["spx_close"].iloc[1] == 100.0
        assert result["spx_close"].iloc[2] == 200.0
        assert pd.isna(result["vix"].iloc[0])
        assert result["vix"].iloc[1] == 15.0

    def test_does_not_modify_original(self):
        frame = pd.DataFrame(
            {DATE_COLUMN: ["2025-01-02"], "spx_close": [100.0]}
        )
        apply_lag(frame)
        assert frame["spx_close"].iloc[0] == 100.0


# ── staleness & completeness ────────────────────────────────────────────

class TestStaleness:
    def _iso(self, dates: list[str], values: list[float]) -> pd.Series:
        return pd.Series(values, index=pd.Index(dates, name=DATE_COLUMN))

    def test_none_for_fresh_series(self):
        dates = ["2025-01-02", "2025-01-03", "2025-01-06"]
        series = self._iso(dates, [10.0, 11.0, 12.0])
        assert _staleness_reason(series, date(2025, 1, 10)) is None

    def test_flags_mostly_identical_values(self):
        series = self._iso(["2025-01-02", "2025-01-03", "2025-01-06"], [7.4, 7.4, 7.4])
        reason = _staleness_reason(series, date(2025, 1, 10))
        assert reason is not None
        assert "identical" in reason

    def test_flags_series_ending_before_window(self):
        # Last data point 40 days before the requested end -> stale.
        series = self._iso(["2025-01-02", "2025-01-03"], [10.0, 11.0])
        reason = _staleness_reason(series, date(2025, 3, 1))
        assert reason is not None
        assert "before the requested end" in reason

    def test_returns_none_for_empty(self):
        assert _staleness_reason(pd.Series(dtype=float), date(2025, 1, 10)) is None


class TestCompleteness:
    def test_full_window_is_1(self):
        series = pd.Series(
            [1.0] * 5,
            index=pd.Index(pd.bdate_range("2025-01-06", periods=5).strftime("%Y-%m-%d")),
        )
        assert _completeness(series, date(2025, 1, 6), date(2025, 1, 10)) == 1.0

    def test_partial_series_scores_low(self):
        # One business day covered out of a five-day week.
        series = pd.Series([1.0], index=pd.Index(["2025-01-06"]))
        assert _completeness(series, date(2025, 1, 6), date(2025, 1, 10)) == pytest.approx(0.2)

    def test_empty_series_scores_zero(self):
        assert _completeness(pd.Series(dtype=float), date(2025, 1, 6), date(2025, 1, 10)) == 0.0


# ── override CSVs ───────────────────────────────────────────────────────

class TestOverride:
    def test_override_replaces_existing_column(self, tmp_path):
        path = tmp_path / "credit_spread_hy.csv"
        path.write_text(
            "date,value\n2024-01-02,3.0\n2024-01-03,3.1\n2024-01-06,3.2\n",
            encoding="utf-8",
        )
        placed = {"credit_spread_hy": pd.Series(
            [9.0], index=pd.Index(["2024-01-02"], name=DATE_COLUMN)
        )}
        report = ExtractionReport(rows=1)

        _apply_override(placed, report, "credit_spread_hy", path)

        # The manual export is authoritative: its value replaces the automated
        # one on every overlapping date, not just the ones left blank.
        assert placed["credit_spread_hy"]["2024-01-02"] == 3.0
        assert placed["credit_spread_hy"]["2024-01-03"] == 3.1
        assert placed["credit_spread_hy"]["2024-01-06"] == 3.2

    def test_override_gap_fills_only_dates_the_export_lacks(self, tmp_path):
        # A date the export cannot cover keeps the automated source's value —
        # replacement on overlap, fallback elsewhere.
        path = tmp_path / "credit_spread_hy.csv"
        path.write_text(
            "date,value\n2024-01-02,3.0\n",
            encoding="utf-8",
        )
        placed = {"credit_spread_hy": pd.Series(
            [9.0, 9.5], index=pd.Index(["2024-01-02", "2024-01-03"], name=DATE_COLUMN)
        )}
        report = ExtractionReport(rows=1)

        _apply_override(placed, report, "credit_spread_hy", path)

        assert placed["credit_spread_hy"]["2024-01-02"] == 3.0  # export wins
        assert placed["credit_spread_hy"]["2024-01-03"] == 9.5  # covered only by auto

    def test_places_column_when_absent(self, tmp_path):
        path = tmp_path / "credit_spread_hy.csv"
        path.write_text("date,value\n2024-01-02,3.0\n", encoding="utf-8")
        report = ExtractionReport(rows=0)

        _apply_override({}, report, "credit_spread_hy", path)

        assert list(report.derived) == ["credit_spread_hy (override)"]

    def test_missing_file_is_noop(self, tmp_path):
        report = ExtractionReport(rows=0)
        _apply_override({}, report, "credit_spread_hy", tmp_path / "nope.csv")
        assert report.derived == []

    def test_skips_file_without_value_column(self, tmp_path):
        path = tmp_path / "credit_spread_hy.csv"
        path.write_text("date\n2024-01-02\n", encoding="utf-8")
        report = ExtractionReport(rows=0)
        _apply_override({}, report, "credit_spread_hy", path)
        assert report.derived == []

    def test_accepts_bloomberg_style_override(self, tmp_path):
        # Dates + PX_LAST headers, USB-style dates with a time component.
        path = tmp_path / "credit_spread_hy.csv"
        path.write_text(
            "Dates,PX_LAST\n01/02/2024 12:00,3.0\n01/03/2024 12:00,3.1\n",
            encoding="utf-8",
        )
        placed = {"credit_spread_hy": pd.Series(
            [9.0], index=pd.Index(["2024-01-02"], name=DATE_COLUMN)
        )}
        report = ExtractionReport(rows=1)

        _apply_override(placed, report, "credit_spread_hy", path)

        # The Bloomberg export replaces the FRED value on the shared date.
        assert placed["credit_spread_hy"]["2024-01-02"] == 3.0
        assert placed["credit_spread_hy"]["2024-01-03"] == 3.1
        assert "credit_spread_hy (override)" in report.derived

    def test_skips_malformed_file_silently(self, tmp_path):
        path = tmp_path / "credit_spread_hy.csv"
        path.write_text("ticker,rate\nABC,1.5\nDEF,2.5\n", encoding="utf-8")
        report = ExtractionReport(rows=0)
        _apply_override({}, report, "credit_spread_hy", path)
        assert report.derived == []

    def test_repeated_dates_in_the_override_collapse(self, tmp_path):
        # An export re-emitting a date must yield one value per date, or the
        # downstream duplicate-date guard fires.  Last row wins.
        path = tmp_path / "credit_spread_hy.csv"
        path.write_text(
            "date,value\n2024-01-02,3.0\n2024-01-02,3.2\n2024-01-03,3.1\n",
            encoding="utf-8",
        )
        placed = {"credit_spread_hy": pd.Series(
            [9.0], index=pd.Index(["2024-01-02"], name=DATE_COLUMN)
        )}
        report = ExtractionReport(rows=1)

        _apply_override(placed, report, "credit_spread_hy", path)

        s = placed["credit_spread_hy"]
        assert int(s.index.duplicated().sum()) == 0
        assert s["2024-01-02"] == 3.2  # the last of the two repeats
        assert s["2024-01-03"] == 3.1


# ── extract_all ─────────────────────────────────────────────────────────

class TestExtractAll:
    @patch("forecasting_engine.ingest.extract.extract_french")
    @patch("forecasting_engine.ingest.extract.yf")
    @patch("forecasting_engine.ingest.extract.fredapi.Fred")
    def test_full_extraction(self, mock_fred_cls, mock_yf, mock_french):
        mock_french.return_value = ({}, [], [])
        dates = pd.bdate_range("2025-01-02", periods=5).strftime("%Y-%m-%d").tolist()
        mock_yf.download.return_value = _make_yahoo_frame(
            list(YAHOO_SERIES.values()), dates
        )
        instance = mock_fred_cls.return_value
        instance.get_series.side_effect = lambda sid, **kw: _make_fred_series(dates)

        frame, report = extract_all("test-key", date(2025, 1, 1), date(2025, 1, 10))

        # extract_french is mocked out here (returns nothing), so the FF
        # columns are absent from this Yahoo+FRED-only frame.
        expected = set(ALL_COLUMNS) - set(MANUAL_COLUMNS) - {
            "ff_mkt_rf", "ff_smb", "ff_hml", "ff_rmw", "ff_cma", "ff_rf",
        }
        assert expected.issubset(frame.columns)
        assert report.rows > 0
        assert report.start is not None

    @patch("forecasting_engine.ingest.extract.extract_french")
    @patch("forecasting_engine.ingest.extract.yf")
    @patch("forecasting_engine.ingest.extract.fredapi.Fred")
    def test_reports_completeness_and_staleness(self, mock_fred_cls, mock_yf, mock_french):
        mock_french.return_value = ({}, [], [])
        dates = pd.bdate_range("2025-01-02", periods=5).strftime("%Y-%m-%d").tolist()
        mock_yf.download.return_value = _make_yahoo_frame(
            list(YAHOO_SERIES.values()), dates
        )
        instance = mock_fred_cls.return_value
        instance.get_series.side_effect = lambda sid, **kw: _make_fred_series(dates)

        frame, report = extract_all("test-key", date(2025, 1, 1), date(2025, 1, 10))

        assert "spx_close" in report.completeness
        assert "spx_close_target" in report.completeness
        assert report.completeness["spx_close_target"] == report.completeness["spx_close"]
        assert 0.0 <= report.completeness["spx_close"] <= 1.0
        assert isinstance(report.stale, dict)

    @patch("forecasting_engine.ingest.extract.extract_french")
    @patch("forecasting_engine.ingest.extract.yf")
    @patch("forecasting_engine.ingest.extract.fredapi.Fred")
    def test_targets_are_unlagged_observed_levels(self, mock_fred_cls, mock_yf, mock_french):
        mock_french.return_value = ({}, [], [])
        dates = pd.bdate_range("2025-01-02", periods=5).strftime("%Y-%m-%d").tolist()
        mock_yf.download.return_value = _make_yahoo_frame(
            list(YAHOO_SERIES.values()), dates
        )
        instance = mock_fred_cls.return_value
        instance.get_series.side_effect = lambda sid, **kw: _make_fred_series(dates)

        frame, report = extract_all("test-key", date(2025, 1, 1), date(2025, 1, 10))

        # spx_close is lagged (row t carries the t-1 observation) while
        # spx_close_target keeps the t observation the model forecasts the
        # return of, so the two are the same series offset by one row.
        assert "spx_close_target" in frame.columns
        assert "bond_index_target" in frame.columns
        assert frame["spx_close_target"].iloc[0] == frame["spx_close"].iloc[1]
        assert frame["spx_close_target"].iloc[1] == frame["spx_close"].iloc[2]
        assert frame["bond_index_target"].iloc[0] == frame["bond_index_global_agg"].iloc[1]
        assert not pd.isna(frame["spx_close_target"].iloc[0])  # not lagged, so row 0 is alive
        assert "spx_close_target" in report.completeness

    @patch("forecasting_engine.ingest.extract.extract_french")
    @patch("forecasting_engine.ingest.extract.yf")
    @patch("forecasting_engine.ingest.extract.fredapi.Fred")
    def test_partial_failure_still_returns_data(self, mock_fred_cls, mock_yf, mock_french):
        mock_french.return_value = ({}, [], [])
        dates = pd.bdate_range("2025-01-02", periods=3).strftime("%Y-%m-%d").tolist()
        mock_yf.download.return_value = _make_yahoo_frame(
            list(YAHOO_SERIES.values()), dates
        )
        instance = mock_fred_cls.return_value
        instance.get_series.side_effect = RuntimeError("API down")

        frame, report = extract_all("test-key", date(2025, 1, 1), date(2025, 1, 10))

        assert "spx_close" in report.yahoo_ok
        assert "vix" in report.yahoo_ok
        assert len(report.fred_failed) > 0
        assert not report.all_ok
        assert len(frame) > 0


# ── to_accepted ─────────────────────────────────────────────────────────

class TestToAccepted:
    def test_produces_source_with_hash(self):
        frame = pd.DataFrame(
            {DATE_COLUMN: ["2025-01-02"], "spx_close": [100.0]}
        )
        report = ExtractionReport(rows=1, start="2025-01-02", end="2025-01-02")
        source = to_accepted(frame, report)

        assert source.sha256
        assert source.name.startswith("extracted_")
        assert source.size_bytes > 0


# ── merge_manual_columns ────────────────────────────────────────────────

class TestMergeManualColumns:
    def _frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {DATE_COLUMN: ["2025-01-02", "2025-01-03", "2025-01-06"],
             "spx_close": [100.0, 200.0, 300.0]}
        )

    def _csv(self, header: str, rows: str) -> bytes:
        return f"{header}\n{rows}".encode()

    def test_merges_column_by_date(self):
        frame = self._frame()
        csv_bytes = self._csv(
            "date,bond_index_global_agg", "2025-01-02,10.5\n2025-01-03,11.0\n2025-01-06,12.5"
        )
        result = merge_manual_columns(frame, "bond_index_global_agg", csv_bytes)

        assert "bond_index_global_agg" in result.columns
        assert result["bond_index_global_agg"].tolist() == [10.5, 11.0, 12.5]
        assert result["spx_close"].tolist() == [100.0, 200.0, 300.0]

    def test_partial_overlap_leaves_nan(self):
        frame = self._frame()
        csv_bytes = self._csv("date,value", "2025-01-02,9.0")
        result = merge_manual_columns(frame, "fx_impl_vol", csv_bytes)

        assert result["fx_impl_vol"].iloc[0] == 9.0
        assert pd.isna(result["fx_impl_vol"].iloc[1])
        assert pd.isna(result["fx_impl_vol"].iloc[2])

    def test_rejects_csv_without_value_column(self):
        frame = self._frame()
        with pytest.raises(ValueError):
            merge_manual_columns(frame, "bond_index_global_agg", b"date\n2025-01-02\n")

    @pytest.mark.parametrize(
        "header,row1,row2,row3",
        [
            # Documented format: a literal date header, ISO dates.
            ("date,value", "2025-01-02,10.5", "2025-01-03,11.0", "2025-01-06,12.5"),
            # Bloomberg export: Dates header with date+time strings.
            (
                "Dates,PX_LAST",
                "2025-01-02 00:00:00,10.5",
                "2025-01-03 00:00:00,11.0",
                "2025-01-06 00:00:00,12.5",
            ),
            # Bloomberg export: Date header with US-style dates.
            (
                "Date,PX_LAST",
                "01/02/2025,10.5",
                "01/03/2025,11.0",
                "01/06/2025,12.5",
            ),
        ],
    )
    def test_merges_across_header_shapes(self, header, row1, row2, row3):
        frame = self._frame()
        csv_bytes = self._csv(header, f"{row1}\n{row2}\n{row3}")
        result = merge_manual_columns(frame, "bond_index_global_agg", csv_bytes)

        assert result["bond_index_global_agg"].tolist() == [10.5, 11.0, 12.5]
        assert result[DATE_COLUMN].tolist() == ["2025-01-02", "2025-01-03", "2025-01-06"]

    def test_manual_values_replace_extracted_same_name(self):
        # The CSV covers only 2025-01-02 and 2025-01-06, so the manual value
        # replaces the automated one where present and 2025-01-03 stays NaN.
        frame = pd.DataFrame(
            {DATE_COLUMN: ["2025-01-02", "2025-01-03", "2025-01-06"],
             "bond_index_global_agg": [99.0, 99.0, 99.0]}
        )
        csv_bytes = self._csv("Date,PX_LAST", "01/02/2025,10.5\n01/06/2025,12.5")
        result = merge_manual_columns(frame, "bond_index_global_agg", csv_bytes)

        assert result["bond_index_global_agg"].iloc[0] == 10.5
        assert pd.isna(result["bond_index_global_agg"].iloc[1])
        assert result["bond_index_global_agg"].iloc[2] == 12.5

    def test_manual_file_extends_dates_the_frame_lacks(self):
        # A fresh manual column's coverage is its own: a date before the frame's
        # window stays in the output (outer join), instead of being clipped.
        frame = pd.DataFrame(
            {DATE_COLUMN: ["2025-01-06"],
             "spx_close": [300.0]}
        )
        csv_bytes = self._csv("date,value", "2025-01-02,9.0\n2025-01-06,12.0")
        result = merge_manual_columns(frame, "fx_impl_vol", csv_bytes)

        assert result[DATE_COLUMN].tolist() == ["2025-01-02", "2025-01-06"]
        assert result["fx_impl_vol"].tolist() == [9.0, 12.0]
        assert pd.isna(result["spx_close"].iloc[0])  # no automated value that day

    def test_manual_values_replace_extracted_same_name_outer(self):
        # Same contract as the same-name test, but the manual file also reaches
        # one day before the frame: that day survives and carries the manual
        # value, and an uncovered automated date goes NaN (the manual source
        # owns the column once selected — no spliced auto values).
        frame = pd.DataFrame(
            {DATE_COLUMN: ["2025-01-02", "2025-01-03"],
             "bond_index_global_agg": [99.0, 99.0]}
        )
        csv_bytes = self._csv(
            "Date,PX_LAST",
            "2024-12-31,10.5\n2025-01-02,12.5",
        )
        result = merge_manual_columns(frame, "bond_index_global_agg", csv_bytes)

        assert result[DATE_COLUMN].tolist() == ["2024-12-31", "2025-01-02", "2025-01-03"]
        assert result["bond_index_global_agg"].iloc[:2].tolist() == [10.5, 12.5]
        assert pd.isna(result["bond_index_global_agg"].iloc[2])

    def test_repeated_dates_in_the_manual_file_collapse_to_one_row(self):
        # A daily export can carry several rows for one date (intraday
        # timestamps).  They must collapse before the outer join — otherwise
        # clean_output's duplicate-date guard fires on the manual file itself.
        frame = self._frame()
        csv_bytes = self._csv(
            "Date,PX_LAST",
            "2025-01-02,10.5\n" + ("2025-01-02,10.5\n" * 23) + "2025-01-03,11.0\n",
        )
        result = merge_manual_columns(frame, "bond_index_global_agg", csv_bytes)

        assert int(result[DATE_COLUMN].duplicated().sum()) == 0
        assert result["bond_index_global_agg"].iloc[:2].tolist() == [10.5, 11.0]
        assert pd.isna(result["bond_index_global_agg"].iloc[2])

        from forecasting_engine.ingest.extract import clean_output

        out, _ = clean_output(result)  # must not raise on duplicates
        assert out[DATE_COLUMN].is_unique

    def test_tolerates_utf8_bom(self):
        frame = self._frame()
        csv_bytes = b"\xef\xbb\xbfDate,PX_LAST\n2025-01-02,10.5\n2025-01-03,11.0\n"
        result = merge_manual_columns(frame, "bond_index_global_agg", csv_bytes)

        assert result["bond_index_global_agg"].tolist()[:2] == [10.5, 11.0]

    def test_rejects_csv_without_date_column(self):
        frame = self._frame()
        csv_bytes = self._csv("ticker,rate", "ABC,1.5\nDEF,2.5")
        with pytest.raises(ValueError, match="no date column found"):
            merge_manual_columns(frame, "bond_index_global_agg", csv_bytes)
