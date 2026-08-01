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


def test_missing_date_does_not_hide_other_problems():
    frame = valid_frame().drop(columns=["date"])
    frame.loc[1, "vix"] = 300.0
    kinds = {i.kind for i in schema.validate(frame)}
    assert kinds == {"missing_column", "out_of_range"}


def test_missing_column_detail_names_the_series():
    frame = valid_frame().drop(columns=["credit_spread_hy"])
    detail = schema.validate(frame)[0].detail
    spec = next(c for c in schema.COLUMNS if c.name == "credit_spread_hy")
    assert "credit_spread_hy" in detail
    assert spec.description in detail


def test_unparseable_date_is_reported():
    frame = valid_frame()
    frame.loc[1, "date"] = "not-a-date"
    issues = [i for i in schema.validate(frame) if i.kind == "unparseable_date"]
    assert len(issues) == 1
    assert issues[0].count == 1


def test_value_above_the_ceiling_is_out_of_range():
    frame = valid_frame()
    frame.loc[1, "vix"] = 300.0
    issues = [i for i in schema.validate(frame) if i.kind == "out_of_range"]
    assert len(issues) == 1
    assert "above" in issues[0].detail


def test_multiple_issues_accumulate():
    frame = valid_frame()
    frame.loc[1, "vix"] = -3.0
    frame["term_spread"] = frame["term_spread"].astype(object)
    frame.loc[2, "term_spread"] = "oops"
    kinds = {i.kind for i in schema.validate(frame)}
    assert {"out_of_range", "non_numeric"} <= kinds


def test_blocking_keeps_only_unusable_issues():
    issues = [
        schema.SchemaIssue("missing_column", "vix", "absent"),
        schema.SchemaIssue("duplicate_date", "date", "repeated"),
        schema.SchemaIssue("non_numeric", "vix", "bad"),
    ]
    assert [i.kind for i in schema.blocking(issues)] == ["missing_column", "non_numeric"]


def test_repairable_issues_are_not_blocking():
    issues = [
        schema.SchemaIssue("duplicate_date", "date", "repeated"),
        schema.SchemaIssue("unsorted_dates", "date", "unsorted"),
        schema.SchemaIssue("out_of_range", "vix", "high"),
    ]
    assert schema.blocking(issues) == []
