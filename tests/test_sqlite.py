"""X2-22 (б): one read-only open of a SQLite database someone else writes."""

import sqlite3

import pytest

from agentkit.sqlite import open_ro


def test_reads_and_never_writes(tmp_path):
    path = tmp_path / "odd ?name#.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE t (x)")
    db.execute("INSERT INTO t VALUES (1)")
    db.commit()
    db.close()
    conn = open_ro(path, timeout=0.5)
    try:
        assert conn.execute("SELECT count(*) FROM t").fetchone() == (1,)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("INSERT INTO t VALUES (2)")
    finally:
        conn.close()


def test_a_missing_database_is_an_error_not_a_new_file(tmp_path):
    with pytest.raises(sqlite3.OperationalError):
        open_ro(tmp_path / "missing.db")
    assert not (tmp_path / "missing.db").exists()
