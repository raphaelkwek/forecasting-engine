"""Parsing the Fama-French 5-factor daily CSV out of its zip.

The real file wraps the data table in explanatory prose with no fixed line
count, so these fixtures vary the amount of surrounding text to prove the
parser finds the table by content, not by position.
"""

import io
import zipfile

import pandas as pd

from forecasting_engine.extraction.fama_french import parse, restrict_to

CSV_BODY = """This file was created by CMPT_ME_BEME_OP_INV_RETS.
Copyright 2024 Kenneth R. French

,Mkt-RF,SMB,HML,RMW,CMA,RF
19630701,-0.67,0.02,-0.35,0.03,0.13,0.01
19630702,0.79,-0.28,0.28,-0.08,-0.20,0.01

Copyright 2024 Kenneth R. French. All rights reserved.
"""


def zip_bytes(body: str = CSV_BODY) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("F-F_Research_Data_5_Factors_2x3_daily.CSV", body)
    return buffer.getvalue()


def test_preamble_and_footer_prose_are_stripped():
    frame = parse(zip_bytes())
    assert len(frame) == 2


def test_only_rows_with_an_8_digit_date_are_kept():
    frame = parse(zip_bytes())
    assert list(frame["Date"]) == list(pd.to_datetime(["1963-07-01", "1963-07-02"]))


def test_columns_are_the_five_factors_plus_rf():
    frame = parse(zip_bytes())
    assert list(frame.columns) == ["Date", "Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF"]


def test_values_are_numeric():
    frame = parse(zip_bytes())
    assert frame["Mkt-RF"].iloc[0] == -0.67


def test_a_longer_preamble_does_not_shift_the_result():
    longer = "extra line one\nextra line two\nextra line three\n" + CSV_BODY
    frame = parse(zip_bytes(longer))
    assert len(frame) == 2


# --- restricting to a date range ----------------------------------------


def test_restrict_to_keeps_only_the_requested_range():
    frame = parse(zip_bytes())
    restricted = restrict_to(
        frame, pd.Timestamp("1963-07-02"), pd.Timestamp("1963-07-02")
    )
    assert list(restricted["Date"]) == [pd.Timestamp("1963-07-02")]


def test_restrict_to_an_end_past_the_data_just_returns_what_exists():
    frame = parse(zip_bytes())
    restricted = restrict_to(
        frame, pd.Timestamp("1963-07-01"), pd.Timestamp("2030-01-01")
    )
    assert len(restricted) == 2
