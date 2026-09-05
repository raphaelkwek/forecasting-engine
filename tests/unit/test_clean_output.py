"""Unit tests for ``extract.clean_output``, the final-output contract trim."""

from __future__ import annotations

import pandas as pd
import pytest

from forecasting_engine.ingest.extract import CleaningSummary, clean_output


def _frame(n: int = 4) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [f"2024-01-{i:02d}" for i in range(1, n + 1)],
            "spx_close": [100.0 + i for i in range(n)],
            "bond_index_target": [50.0 + i for i in range(n)],
            "credit_spread_hy": [3.0 + i for i in range(n)],
            "vix": [15.0 - i for i in range(n)],
        }
    )


def test_both_named_columns_are_dropped() -> None:
    frame, summary = clean_output(_frame())
    assert "bond_index_target" not in frame.columns
    assert "credit_spread_hy" not in frame.columns
    assert summary.dropped_columns == ("bond_index_target", "credit_spread_hy")


def test_absent_drop_column_names_are_tolerated() -> None:
    frame = _frame().drop(columns=["credit_spread_hy"])
    out, summary = clean_output(frame)
    assert "bond_index_target" not in out.columns
    assert "spx_close" in out.columns and "vix" in out.columns
    assert summary.dropped_columns == ("bond_index_target",)


def test_a_single_null_drops_the_row_and_nothing_is_filled() -> None:
    frame = _frame()
    frame.loc[1, "vix"] = float("nan")
    out, summary = clean_output(frame)
    assert len(out) == 3
    assert out["vix"].isna().sum() == 0  # NaN removed, not imputed
    assert out["date"].is_unique
    assert summary.rows_before == 4
    assert summary.rows_after == 3


def test_all_null_in_an_optional_column_does_not_drop_rows() -> None:
    # credit_spread_ig is optional — all-null should NOT drop rows.
    # Only REQUIRED columns (date, spx_close, vix) enforce non-null.
    frame = _frame()
    frame["credit_spread_ig"] = float("nan")
    out, summary = clean_output(frame)
    assert len(out) == 4  # all rows kept
    assert summary.rows_after == 4


def test_all_null_in_a_required_column_drops_all_rows() -> None:
    # REQUIRED columns (spx_close, vix) — all-null drops everything.
    frame = _frame()
    frame["spx_close"] = float("nan")
    out, summary = clean_output(frame)
    assert out.empty
    assert summary.rows_after == 0
    assert summary.start is None
    assert summary.end is None


def test_duplicate_dates_raise_value_error() -> None:
    frame = _frame()
    frame.loc[3, "date"] = "2024-01-02"
    with pytest.raises(ValueError, match="duplicate dates"):
        clean_output(frame)


def test_an_unsorted_input_comes_back_sorted_ascending() -> None:
    frame = _frame().iloc[::-1].reset_index(drop=True)
    out, _ = clean_output(frame)
    assert out["date"].tolist() == ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]


def test_the_summary_records_the_typical_case() -> None:
    frame = _frame()
    frame.loc[0, "vix"] = float("nan")
    out, summary = clean_output(frame)
    assert isinstance(summary, CleaningSummary)
    assert summary.rows_before == 4
    assert summary.rows_after == 3
    assert summary.dropped_columns == ("bond_index_target", "credit_spread_hy")
    assert summary.start == "2024-01-02"
    assert summary.end == "2024-01-04"


def test_missing_date_column_raises() -> None:
    frame = _frame().drop(columns=["date"])
    with pytest.raises(ValueError, match="date"):
        clean_output(frame)


def test_custom_drop_columns_override() -> None:
    out, summary = clean_output(_frame(), drop_columns=("vix", "not_there"))
    assert "vix" not in out.columns
    assert "bond_index_target" in out.columns
    assert summary.dropped_columns == ("vix",)


def test_null_in_an_exempt_column_does_not_drop_the_row() -> None:
    # eur_fx_vol trails blank by design; a row with every non-exempt column
    # present survives even though it carries the blank.
    frame = _frame(n=3)
    frame["eur_fx_vol"] = [10.0, 10.5, float("nan")]
    out, summary = clean_output(frame)

    assert len(out) == 3
    assert summary.rows_after == 3
    assert pd.isna(out["eur_fx_vol"].iloc[2])
    assert "eur_fx_vol" in summary.exempt_columns


def test_all_ff_columns_are_exempt_by_default() -> None:
    # The ff_* factors trail the newest month by Ken French's publishing
    # schedule; they are exempted by default so the newest rows survive.
    frame = _frame(n=3)
    for i, col in enumerate(
        ["ff_mkt_rf", "ff_smb", "ff_hml", "ff_rmw", "ff_cma", "ff_rf"]
    ):
        frame[col] = [0.01, 0.02, float("nan") if i % 2 == 0 else 0.03]
    out, summary = clean_output(frame)

    assert len(out) == 3
    assert set(summary.exempt_columns) == {
        "ff_mkt_rf",
        "ff_smb",
        "ff_hml",
        "ff_rmw",
        "ff_cma",
        "ff_rf",
    }


def test_a_null_outside_the_exempt_set_still_drops_the_row() -> None:
    frame = _frame(n=3)
    frame["eur_fx_vol"] = [10.0, 10.5, float("nan")]
    frame.loc[1, "vix"] = float("nan")  # vix is not exempt
    out, summary = clean_output(frame)

    assert len(out) == 2
    assert summary.rows_after == 2


def test_required_columns_are_never_fully_exempted() -> None:
    """Even when a required column is in the exempt set, it is still enforced."""
    frame = _frame(n=3)
    frame.loc[1, "vix"] = float("nan")
    out, _ = clean_output(
        frame, drop_columns=(), exempt_columns=(*_frame().columns, "missing")
    )
    # vix row dropped because required columns override exemption
    assert len(out) == 2