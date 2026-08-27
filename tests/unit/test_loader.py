import pandas as pd
import pytest

from forecasting_engine import fixtures
from forecasting_engine.ingest import loader


@pytest.fixture
def clean_csv(tmp_path):
    path = tmp_path / "clean.csv"
    fixtures.generate(years=2, seed=3, with_defects=False).to_csv(path, index=False)
    return path


@pytest.fixture
def defective_csv(tmp_path):
    path = tmp_path / "defective.csv"
    fixtures.generate(years=5, seed=3, with_defects=True).to_csv(path, index=False)
    return path


def test_clean_file_loads_with_no_issues(clean_csv):
    raw = loader.load(clean_csv)
    assert raw.issues == ()
    assert isinstance(raw.frame.index, pd.DatetimeIndex)
    assert raw.frame.index.is_monotonic_increasing


def test_source_records_a_content_hash(clean_csv):
    raw = loader.load(clean_csv)
    assert len(raw.source.sha256) == 64
    assert raw.source.rows == len(raw.frame)


def test_same_content_hashes_identically(clean_csv, tmp_path):
    copy = tmp_path / "copy.csv"
    copy.write_bytes(clean_csv.read_bytes())
    assert loader.load(clean_csv).source.sha256 == loader.load(copy).source.sha256


def test_duplicate_dates_are_dropped_keeping_the_last(defective_csv):
    raw = loader.load(defective_csv)
    assert not raw.frame.index.duplicated().any()


def test_repairable_issues_are_reported_not_raised(defective_csv):
    raw = loader.load(defective_csv)
    assert any(issue.kind == "duplicate_date" for issue in raw.issues)


def test_missing_column_raises(tmp_path):
    path = tmp_path / "broken.csv"
    fixtures.generate(years=2, seed=3, with_defects=False).drop(columns=["vix"]).to_csv(
        path, index=False
    )
    with pytest.raises(loader.SchemaError, match="vix"):
        loader.load(path)


def test_strict_false_allows_blocking_issues_through(tmp_path):
    path = tmp_path / "broken.csv"
    fixtures.generate(years=2, seed=3, with_defects=False).drop(columns=["vix"]).to_csv(
        path, index=False
    )
    raw = loader.load(path, strict=False)
    assert any(issue.kind == "missing_column" for issue in raw.issues)


def test_unsorted_input_is_sorted_on_load(tmp_path):
    path = tmp_path / "unsorted.csv"
    frame = fixtures.generate(years=2, seed=3, with_defects=False)
    frame.iloc[::-1].to_csv(path, index=False)
    raw = loader.load(path)
    assert raw.frame.index.is_monotonic_increasing
