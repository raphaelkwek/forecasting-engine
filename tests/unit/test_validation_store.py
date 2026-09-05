"""The DuckDB validation log."""

from datetime import datetime

import pytest

from forecasting_engine.ingest.upload import accept_upload
from forecasting_engine.ingest.validation import validate_upload
from forecasting_engine.store.validations import (
    latest_validation,
    recent_validations,
    record_validation,
)

HEADER = (
    "date,spx_close,bond_index_global_agg,vix,tnx_close,dollar_index,"
    "eur_fx_vol,credit_spread_ig,"
    "credit_spread_hy,breakeven_5y,breakeven_10y,term_spread,fx_impl_vol,"
    "ff_mkt_rf,ff_smb,ff_hml,ff_rmw,ff_cma,ff_rf"
)
GOOD = f"{HEADER}\n2024-01-01,100.0,50.0,15.0,4.0,100.0,10.0,1.0,3.0,2.0,8.0,2.2,10.0,0.05,0.02,0.01,0.02,0.01,0.01\n".encode()  # noqa: E501
BAD_TYPE = f"{HEADER}\n2024-01-01,100.0,50.0,oops,4.0,100.0,10.0,1.0,3.0,2.0,8.0,2.2,10.0,0.05,0.02,0.01,0.02,0.01,0.01\n".encode()  # noqa: E501


@pytest.fixture
def db(tmp_path):
    return tmp_path / "history" / "test.duckdb"


def checked(data: bytes, name: str = "signals.csv"):
    accepted = accept_upload(name, data, uploads_dir=None)
    return validate_upload(accepted)


def test_reading_an_absent_database_creates_it_and_returns_nothing(db):
    assert recent_validations(db_path=db) == []
    assert db.exists()


def test_a_passing_validation_round_trips(db):
    at = datetime(2026, 9, 1, 9, 30)
    record_validation(checked(GOOD), db_path=db, checked_at=at)

    (row,) = recent_validations(db_path=db)
    assert row.filename == "signals.csv"
    assert row.passed is True
    assert row.issue_count == 0
    assert row.blocking_count == 0
    assert row.checked_at == at
    assert row.issues == []


def test_a_failing_validation_keeps_the_issue_detail(db):
    record_validation(checked(BAD_TYPE), db_path=db)

    (row,) = recent_validations(db_path=db)
    assert row.passed is False
    assert row.blocking_count == 1
    (issue,) = row.issues
    assert issue["kind"] == "non_numeric"
    assert issue["column"] == "vix"
    assert issue["rows"] == [2]
    assert issue["blocking"] is True


def test_the_newest_validation_comes_first(db):
    at_eight, at_nine = datetime(2026, 9, 1, 8), datetime(2026, 9, 1, 9)
    record_validation(checked(GOOD, "first.csv"), db_path=db, checked_at=at_eight)
    record_validation(checked(BAD_TYPE, "second.csv"), db_path=db, checked_at=at_nine)

    assert [r.filename for r in recent_validations(db_path=db)] == ["second.csv", "first.csv"]


def test_the_latest_validation_for_a_file_can_be_looked_up(db):
    good = checked(GOOD)
    other = checked(BAD_TYPE, "other.csv")
    record_validation(other, db_path=db, checked_at=datetime(2026, 9, 1, 8))
    record_validation(good, db_path=db, checked_at=datetime(2026, 9, 1, 9))

    found = latest_validation(good.source.sha256, db_path=db)
    assert found is not None
    assert found.passed is True


def test_looking_up_an_unknown_file_returns_nothing(db):
    record_validation(checked(GOOD), db_path=db)
    assert latest_validation("0" * 64, db_path=db) is None


def test_revalidating_the_same_file_keeps_both_attempts(db):
    result = checked(GOOD)
    record_validation(result, db_path=db, checked_at=datetime(2026, 9, 1, 8))
    record_validation(result, db_path=db, checked_at=datetime(2026, 9, 1, 9))

    assert len(recent_validations(db_path=db)) == 2
