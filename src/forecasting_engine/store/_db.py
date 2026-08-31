"""Shared DuckDB connection handling.

Both logs live in one database file and open it the same way, so the open,
create-if-absent and close sequence sits here rather than in each module.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path

import duckdb

#: Gitignored, because ``data/`` is.
DEFAULT_DB_PATH: Path = Path("data/forecasting.duckdb")


@contextlib.contextmanager
def connect(db_path: Path, create_sql: str) -> Iterator[duckdb.DuckDBPyConnection]:
    """Open ``db_path``, creating the file and the caller's table if absent."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute(create_sql)
        yield conn
    finally:
        conn.close()
