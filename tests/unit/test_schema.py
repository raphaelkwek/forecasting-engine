import pandas as pd

from forecasting_engine.ingest import schema


def valid_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "spx_close": [100.0, 101.0, 102.0],
            "agg_close": [50.0, 50.1, 50.2],
            "vix": [15.0, 16.0, 17.0],
            "credit_spread_hy": [3.5, 3.6, 3.7],
            "credit_spread_ig": [1.2, 1.2, 1.3],
            "fx_impl_vol": [8.0, 8.1, 8.2],
            "breakeven_10y": [2.2, 2.2, 2.3],
            "term_spread": [1.0, 1.0, 1.1],
        }
    )


def test_valid_frame_has_no_issues():
    assert schema.validate(valid_frame()) == []


def test_missing_column_is_reported():
    frame = valid_frame().drop(columns=["vix"])
    issues = schema.validate(frame)
    assert [i.kind for i in issues] == ["missing_column"]
    assert issues[0].column == "vix"


def test_duplicate_date_is_reported():
    frame = valid_frame()
    frame.loc[2, "date"] = "2024-01-02"
    kinds = {i.kind for i in schema.validate(frame)}
    assert "duplicate_date" in kinds


def test_unsorted_dates_are_reported():
    frame = valid_frame()
    frame["date"] = ["2024-01-03", "2024-01-02", "2024-01-01"]
    kinds = {i.kind for i in schema.validate(frame)}
    assert "unsorted_dates" in kinds


def test_negative_vix_is_out_of_range():
    frame = valid_frame()
    frame.loc[1, "vix"] = -3.0
    issues = [i for i in schema.validate(frame) if i.kind == "out_of_range"]
    assert len(issues) == 1
    assert issues[0].column == "vix"
    assert issues[0].count == 1


def test_non_numeric_value_is_reported():
    frame = valid_frame()
    frame["vix"] = frame["vix"].astype(object)
    frame.loc[1, "vix"] = "not a number"
    kinds = {i.kind for i in schema.validate(frame)}
    assert "non_numeric" in kinds


def test_blank_cell_is_not_a_non_numeric_error():
    frame = valid_frame()
    frame.loc[1, "vix"] = None
    kinds = {i.kind for i in schema.validate(frame)}
    assert "non_numeric" not in kinds


def test_signal_columns_exclude_prices():
    assert "spx_close" not in schema.SIGNAL_COLUMNS
    assert "vix" in schema.SIGNAL_COLUMNS
