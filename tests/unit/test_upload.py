"""File-level validation of an uploaded CSV.

Column, type and range checks are FYP-8's job and are deliberately absent
here. These tests cover only what makes a file acceptable *as a file*.
"""

import hashlib

import pandas as pd
import pytest

from forecasting_engine.ingest.upload import (
    MAX_UPLOAD_BYTES,
    CsvParseError,
    FileSizeError,
    FileTypeError,
    accept_upload,
    check_extension,
    check_size,
    date_range,
    parse_csv,
)

VALID_CSV = (
    b"date,spx_close,vix\n"
    b"2026-01-02,4750.5,13.2\n"
    b"2026-01-03,4762.1,12.9\n"
    b"2026-01-06,4739.8,14.1\n"
)


# --- file type -------------------------------------------------------------


@pytest.mark.parametrize("filename", ["signals.csv", "SIGNALS.CSV", "a.b.csv"])
def test_csv_extensions_are_accepted(filename):
    check_extension(filename)


@pytest.mark.parametrize("filename", ["book.xlsx", "notes.txt", "data.csv.gz", "noextension"])
def test_other_extensions_are_rejected(filename):
    with pytest.raises(FileTypeError):
        check_extension(filename)


def test_the_type_error_names_the_extension_we_got():
    with pytest.raises(FileTypeError) as exc:
        check_extension("q1-export.xlsx")
    assert ".xlsx" in exc.value.message
    assert ".csv" in exc.value.message


def test_a_renamed_spreadsheet_is_rejected_even_though_it_ends_in_csv():
    # Real xlsx files begin with the PK zip magic number.
    disguised = b"PK\x03\x04\x14\x00\x08\x08\x08\x00" + bytes(range(256))
    with pytest.raises(CsvParseError):
        accept_upload("actually-a-spreadsheet.csv", disguised, uploads_dir=None)


def test_an_empty_file_is_rejected():
    with pytest.raises(CsvParseError):
        parse_csv(b"")


# --- file size -------------------------------------------------------------


def test_a_file_at_exactly_the_limit_is_accepted():
    check_size(MAX_UPLOAD_BYTES, filename="edge.csv")


def test_a_file_one_byte_over_the_limit_is_rejected():
    with pytest.raises(FileSizeError):
        check_size(MAX_UPLOAD_BYTES + 1, filename="edge.csv")


def test_a_file_barely_over_the_limit_gets_an_exact_byte_count():
    # Rounded to megabytes both numbers read "25.0 MB", which would tell the
    # user nothing. Fall back to bytes when the two would look identical.
    with pytest.raises(FileSizeError) as exc:
        check_size(MAX_UPLOAD_BYTES + 23, filename="edge.csv")
    assert "26,214,423 bytes" in exc.value.message
    assert "26,214,400 bytes" in exc.value.message


def test_the_size_error_quotes_both_the_size_and_the_limit():
    with pytest.raises(FileSizeError) as exc:
        check_size(30 * 1024 * 1024, filename="big.csv")
    assert "30.0 MB" in exc.value.message
    assert "25.0 MB" in exc.value.message


def test_size_is_checked_before_the_file_is_parsed():
    # Oversized *and* unparseable: the size error must win, because rejecting
    # on size is what lets us avoid parsing 25 MB of rubbish.
    oversized_junk = b"\x00" * (MAX_UPLOAD_BYTES + 1)
    with pytest.raises(FileSizeError):
        accept_upload("junk.csv", oversized_junk, uploads_dir=None)


# --- parsing and acceptance ------------------------------------------------


def test_a_valid_csv_is_parsed_into_a_frame(tmp_path):
    accepted = accept_upload("signals.csv", VALID_CSV, uploads_dir=tmp_path)

    assert isinstance(accepted.frame, pd.DataFrame)
    assert accepted.row_count == 3
    assert list(accepted.frame.columns) == ["date", "spx_close", "vix"]


def test_the_source_records_the_name_size_and_hash(tmp_path):
    accepted = accept_upload("signals.csv", VALID_CSV, uploads_dir=tmp_path)

    assert accepted.source.name == "signals.csv"
    assert accepted.source.size_bytes == len(VALID_CSV)
    assert accepted.source.sha256 == hashlib.sha256(VALID_CSV).hexdigest()


def test_the_file_is_written_under_its_own_hash(tmp_path):
    accepted = accept_upload("signals.csv", VALID_CSV, uploads_dir=tmp_path)

    assert accepted.source.path == tmp_path / f"{accepted.source.sha256}.csv"
    assert accepted.source.path.read_bytes() == VALID_CSV


def test_the_same_bytes_always_hash_the_same_way(tmp_path):
    first = accept_upload("one-name.csv", VALID_CSV, uploads_dir=tmp_path)
    second = accept_upload("another-name.csv", VALID_CSV, uploads_dir=tmp_path)

    assert first.source.sha256 == second.source.sha256
    assert first.source.path == second.source.path
    assert len(list(tmp_path.iterdir())) == 1


def test_re_uploading_identical_bytes_does_not_rewrite_the_file(tmp_path):
    first = accept_upload("signals.csv", VALID_CSV, uploads_dir=tmp_path)
    written_at = first.source.path.stat().st_mtime_ns

    second = accept_upload("signals.csv", VALID_CSV, uploads_dir=tmp_path)

    assert second.source.path.stat().st_mtime_ns == written_at


def test_the_uploads_directory_is_created_if_absent(tmp_path):
    target = tmp_path / "does" / "not" / "exist"
    accepted = accept_upload("signals.csv", VALID_CSV, uploads_dir=target)
    assert accepted.source.path.exists()


def test_nothing_is_written_when_uploads_dir_is_none():
    accepted = accept_upload("signals.csv", VALID_CSV, uploads_dir=None)
    assert accepted.source.path is None
    assert accepted.row_count == 3


# --- date range (best effort, for the confirmation message) ----------------


def test_date_range_reads_the_first_and_last_date():
    frame = parse_csv(VALID_CSV)
    assert date_range(frame) == ("2026-01-02", "2026-01-06")


def test_date_range_is_none_when_there_is_no_date_column():
    assert date_range(parse_csv(b"a,b\n1,2\n")) is None


def test_date_range_is_none_when_the_dates_do_not_parse():
    assert date_range(parse_csv(b"date,a\nnot-a-date,1\n")) is None
