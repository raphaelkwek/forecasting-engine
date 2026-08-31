import pandas as pd
import pytest

from forecasting_engine.ingest import schema
from forecasting_engine.ingest.upload import parse_csv

_VIX = next(c for c in schema.COLUMNS if c.name == "vix")


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


# --- row locations ---------------------------------------------------------
#
# AC2 requires the specific row *and* column, so an issue carries the CSV line
# numbers of the offending cells. Line numbers are what the user sees in Excel:
# line 1 is the header, so the first data row is line 2.


def test_a_bad_numeric_cell_reports_its_csv_line():
    frame = valid_frame()
    frame["vix"] = frame["vix"].astype(object)
    frame.loc[1, "vix"] = "not a number"

    (issue,) = [i for i in schema.validate(frame) if i.kind == "non_numeric"]
    assert issue.column == "vix"
    assert issue.rows == (3,)  # frame row 1 -> header + 1-based -> line 3


def test_several_bad_cells_report_every_line():
    frame = valid_frame()
    frame["vix"] = frame["vix"].astype(object)
    frame.loc[0, "vix"] = "x"
    frame.loc[2, "vix"] = "y"

    (issue,) = [i for i in schema.validate(frame) if i.kind == "non_numeric"]
    assert issue.rows == (2, 4)
    assert issue.count == 2


def test_an_out_of_range_value_reports_its_line():
    frame = valid_frame()
    frame.loc[1, "vix"] = 300.0

    (issue,) = [i for i in schema.validate(frame) if i.kind == "out_of_range"]
    assert issue.rows == (3,)


def test_an_unparseable_date_reports_its_line():
    frame = valid_frame()
    frame.loc[2, "date"] = "not-a-date"

    (issue,) = [i for i in schema.validate(frame) if i.kind == "unparseable_date"]
    assert issue.rows == (4,)


def test_a_duplicate_date_reports_the_repeat_not_the_original():
    frame = valid_frame()
    frame.loc[2, "date"] = "2024-01-02"

    (issue,) = [i for i in schema.validate(frame) if i.kind == "duplicate_date"]
    assert issue.rows == (4,)


def test_a_missing_column_has_no_rows_because_it_is_a_whole_file_problem():
    frame = valid_frame().drop(columns=["vix"])
    (issue,) = [i for i in schema.validate(frame) if i.kind == "missing_column"]
    assert issue.rows == ()


def test_only_the_first_few_lines_are_listed_but_all_are_counted():
    # A file with thousands of bad cells must not produce thousands of line
    # numbers; the count stays exact so nothing is silently dropped.
    frame = pd.concat([valid_frame()] * 40, ignore_index=True)
    frame["date"] = pd.date_range("2024-01-01", periods=len(frame)).strftime("%Y-%m-%d")
    frame["vix"] = -1.0

    (issue,) = [i for i in schema.validate(frame) if i.kind == "out_of_range"]
    assert issue.count == 120
    assert len(issue.rows) == schema.MAX_REPORTED_ROWS
    assert issue.truncated is True


def test_an_issue_within_the_cap_is_not_marked_truncated():
    frame = valid_frame()
    frame.loc[1, "vix"] = 300.0

    (issue,) = [i for i in schema.validate(frame) if i.kind == "out_of_range"]
    assert issue.truncated is False


def test_the_location_reads_as_a_sentence():
    frame = valid_frame()
    frame.loc[1, "vix"] = 300.0

    (issue,) = [i for i in schema.validate(frame) if i.kind == "out_of_range"]
    assert issue.location == "column 'vix', line 3"


def test_a_truncated_location_says_how_many_more():
    frame = pd.concat([valid_frame()] * 40, ignore_index=True)
    frame["date"] = pd.date_range("2024-01-01", periods=len(frame)).strftime("%Y-%m-%d")
    frame["vix"] = -1.0

    (issue,) = [i for i in schema.validate(frame) if i.kind == "out_of_range"]
    assert issue.location.endswith("and 110 more")


def test_a_whole_file_issue_locates_by_column_alone():
    frame = valid_frame().drop(columns=["vix"])
    (issue,) = [i for i in schema.validate(frame) if i.kind == "missing_column"]
    assert issue.location == "column 'vix'"


def test_an_ambiguous_non_iso_date_is_rejected_rather_than_guessed():
    # 01/02/2024 is 1 February or 2 January depending on the exporter. The
    # contract says ISO, so this is a parse failure, not a coin flip.
    frame = valid_frame()
    frame.loc[1, "date"] = "01/02/2024"

    (issue,) = [i for i in schema.validate(frame) if i.kind == "unparseable_date"]
    assert issue.rows == (3,)


# --- what counts as a blank cell -------------------------------------------
#
# pandas reads a fixed set of tokens as missing. That set decides whether a cell
# is "no data" (reported later by quality checks) or a type error (blocking
# now), so it is worth pinning: Bloomberg exports carry #N/A heavily, and the
# difference is invisible to whoever opens the file in Excel.


@pytest.mark.parametrize("token", ["", "n/a", "N/A", "NA", "null", "NULL", "#N/A", "#N/A N/A"])
def test_recognised_blank_tokens_are_missing_data_not_type_errors(token):
    frame = parse_csv(f"date,vix\n2024-01-01,{token}\n".encode())
    issues = [i for i in schema._numeric_issues(frame["vix"], _VIX) if i.kind == "non_numeric"]
    assert issues == []


@pytest.mark.parametrize(
    "token", ["-", "TBD", "not reported", "#N/A Field Not Applicable", "#N/A Invalid Security"]
)
def test_unrecognised_placeholders_are_type_errors(token):
    frame = parse_csv(f"date,vix\n2024-01-01,{token}\n".encode())
    issues = [i for i in schema._numeric_issues(frame["vix"], _VIX) if i.kind == "non_numeric"]
    assert [i.rows for i in issues] == [(2,)]
