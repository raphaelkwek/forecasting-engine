"""Bytes to stored file to logged event, along the path the dashboard takes."""

import pytest

from forecasting_engine.ingest.upload import (
    MAX_UPLOAD_BYTES,
    CsvParseError,
    FileSizeError,
    FileTypeError,
    accept_upload,
)
from forecasting_engine.store.uploads import recent_uploads, record_upload

SIGNALS_CSV = (
    b"date,spx_close,agg_close,vix,credit_spread_hy,credit_spread_ig,"
    b"fx_impl_vol,breakeven_10y,term_spread\n"
    b"2026-01-02,4750.5,102.3,13.2,3.41,1.12,8.4,2.31,0.62\n"
    b"2026-01-05,4762.1,102.1,12.9,3.38,1.11,8.3,2.33,0.64\n"
    b"2026-01-06,4739.8,102.6,14.1,3.55,1.15,8.9,2.29,0.59\n"
)


@pytest.fixture(autouse=True)
def in_a_scratch_workspace(tmp_path, monkeypatch):
    """Run against the real relative defaults, rooted somewhere disposable."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _upload(filename, data):
    accepted = accept_upload(filename, data)
    record_upload(accepted)
    return accepted


def test_a_valid_upload_is_stored_and_logged(in_a_scratch_workspace):
    accepted = _upload("signals.csv", SIGNALS_CSV)

    stored = in_a_scratch_workspace / "data" / "uploads" / f"{accepted.source.sha256}.csv"
    assert stored.read_bytes() == SIGNALS_CSV

    (row,) = recent_uploads()
    assert row.filename == "signals.csv"
    assert row.sha256 == accepted.source.sha256
    assert row.row_count == 3
    assert row.size_bytes == len(SIGNALS_CSV)


def test_the_parsed_frame_carries_every_column_through(in_a_scratch_workspace):
    accepted = _upload("signals.csv", SIGNALS_CSV)

    assert len(accepted.frame.columns) == 9
    assert "spx_close" in accepted.frame.columns
    assert accepted.frame["vix"].tolist() == [13.2, 12.9, 14.1]


@pytest.mark.parametrize(
    ("filename", "data", "expected"),
    [
        ("book.xlsx", SIGNALS_CSV, FileTypeError),
        ("disguised.csv", b"PK\x03\x04" + bytes(range(256)), CsvParseError),
        ("huge.csv", b"a,b\n" + b"1,2\n" * (MAX_UPLOAD_BYTES // 4), FileSizeError),
    ],
)
def test_a_rejected_upload_writes_nothing_anywhere(filename, data, expected):
    with pytest.raises(expected):
        _upload(filename, data)

    assert recent_uploads() == []


def test_re_uploading_the_same_file_stores_one_copy_but_logs_two_events(
    in_a_scratch_workspace,
):
    _upload("signals.csv", SIGNALS_CSV)
    _upload("signals-renamed.csv", SIGNALS_CSV)

    uploads_dir = in_a_scratch_workspace / "data" / "uploads"
    assert len(list(uploads_dir.iterdir())) == 1

    logged = recent_uploads()
    assert len(logged) == 2
    assert {row.filename for row in logged} == {"signals.csv", "signals-renamed.csv"}
    assert len({row.sha256 for row in logged}) == 1
