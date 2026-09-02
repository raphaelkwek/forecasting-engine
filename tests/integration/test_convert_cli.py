"""The converter command line, end to end onto disk."""

from datetime import datetime

import openpyxl
import pandas as pd
import pytest

from forecasting_engine.convert import main
from forecasting_engine.ingest.upload import accept_upload
from forecasting_engine.ingest.validation import require_valid, validate_upload

DATES = ["2024-01-01", "2024-01-02", "2024-01-03"]

FULL_SET = {
    "SPX Index": (4750.0, 4762.0, 4739.0),
    "LEGATRUU Index": (483.0, 483.8, 481.9),
    "VIX Index": (13.4, 13.5, 12.0),
    "LF98OAS Index": (3.41, 3.38, 3.55),
    "LUACOAS Index": (1.35, 1.36, 1.37),
    "JPMVXYG7 Index": (8.4, 8.3, 8.9),
    "USGGBE10 Index": (2.31, 2.33, 2.29),
    "USGG10YR Index": (4.20, 4.30, 4.10),
    "USGG2YR Index": (3.60, 3.80, 3.70),
}


def workbook(tmp_path, security, values):
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Data"
    sheet.append(["Date", "PX_LAST", "PX_BID"])
    for date, value in zip(DATES, values, strict=True):
        sheet.append([datetime.fromisoformat(date), value, "#N/A N/A"])
    meta = book.create_sheet("Metadata")
    meta.append(["Field", "Value"])
    meta.append(["Security", security])
    path = tmp_path / f"{security.split()[0].lower()}.xlsx"
    book.save(path)
    return path


@pytest.fixture
def exports(tmp_path):
    return [workbook(tmp_path, sec, vals) for sec, vals in FULL_SET.items()]


def test_a_complete_set_converts_and_exits_zero(tmp_path, exports, capsys):
    out = tmp_path / "signals.csv"
    code = main([*map(str, exports), "-o", str(out)])

    assert code == 0
    assert out.exists()
    assert "MISSING" not in capsys.readouterr().out


def test_the_output_passes_schema_validation(tmp_path, exports):
    out = tmp_path / "signals.csv"
    main([*map(str, exports), "-o", str(out)])

    accepted = accept_upload("signals.csv", out.read_bytes(), uploads_dir=None)
    result = validate_upload(accepted)

    assert result.passed, result.describe()
    assert require_valid(accepted, result).frame.shape == (3, 9)


def test_the_output_has_iso_dates_and_contract_columns(tmp_path, exports):
    out = tmp_path / "signals.csv"
    main([*map(str, exports), "-o", str(out)])

    frame = pd.read_csv(out)
    assert list(frame.columns) == [
        "date", "spx_close", "agg_close", "vix", "credit_spread_hy",
        "credit_spread_ig", "fx_impl_vol", "breakeven_10y", "term_spread",
    ]
    assert frame["date"].tolist() == DATES


def test_an_incomplete_set_still_writes_but_exits_nonzero(tmp_path, capsys):
    partial = [
        workbook(tmp_path, "SPX Index", (4750.0, 4762.0, 4739.0)),
        workbook(tmp_path, "VIX Index", (13.4, 13.5, 12.0)),
    ]
    out = tmp_path / "signals.csv"
    code = main([*map(str, partial), "-o", str(out)])

    assert code == 1
    assert out.exists(), "a partial file you can look at beats no file"
    assert "MISSING  agg_close" in capsys.readouterr().out


def test_the_wrong_field_is_caught_before_it_reaches_validation(tmp_path, capsys):
    wrong = dict(FULL_SET)
    wrong["LF98OAS Index"] = (1770.79, 2033.79, 2992.90)  # total return, not a spread
    paths = [workbook(tmp_path, sec, vals) for sec, vals in wrong.items()]
    out = tmp_path / "signals.csv"

    code = main([*map(str, paths), "-o", str(out)])

    assert code == 1
    assert "SUSPECT" in capsys.readouterr().out


def test_a_missing_path_is_refused_before_anything_is_written(tmp_path):
    out = tmp_path / "signals.csv"
    assert main([str(tmp_path / "nope.xlsx"), "-o", str(out)]) == 2
    assert not out.exists()


def test_the_output_directory_is_created(tmp_path, exports):
    out = tmp_path / "nested" / "deeper" / "signals.csv"
    assert main([*map(str, exports), "-o", str(out)]) == 0
    assert out.exists()


def test_the_default_output_lands_in_the_gitignored_data_directory():
    # A CSV in the repository root is untracked and easy to commit by mistake.
    from forecasting_engine.convert import DEFAULT_OUT

    assert DEFAULT_OUT.parts[0] == "data"
