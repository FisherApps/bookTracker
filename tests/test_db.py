"""Tests for src.db — schema, inserts, dedupe."""

import sqlite3

import pytest

from src.db import get_connection, insert_failure, insert_snapshot, query_snapshots


@pytest.fixture()
def conn(tmp_path):
    return get_connection(tmp_path / "test.db")


class TestSchema:
    def test_schema_creation_is_idempotent(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn1 = get_connection(db_path)
        conn1.close()
        # Second call should not raise
        conn2 = get_connection(db_path)
        conn2.close()


class TestSnapshots:
    def test_insert_and_query(self, conn):
        insert_snapshot(
            conn,
            asin="B0GY7T45YS",
            captured_at="2026-05-25T04:00:00+00:00",
            capture_date="2026-05-25",
            category_id="books",
            category_name="Books",
            rank=857576,
        )
        rows = query_snapshots(conn, "B0GY7T45YS")
        assert len(rows) == 1
        assert rows[0]["rank"] == 857576

    def test_duplicate_is_ignored(self, conn):
        kwargs = dict(
            asin="B0GY7T45YS",
            captured_at="2026-05-25T04:00:00+00:00",
            capture_date="2026-05-25",
            category_id="books",
            category_name="Books",
            rank=857576,
        )
        assert insert_snapshot(conn, **kwargs) is True
        assert insert_snapshot(conn, **kwargs) is False
        rows = query_snapshots(conn, "B0GY7T45YS")
        assert len(rows) == 1

    def test_query_returns_date_order(self, conn):
        for date in ["2026-05-27", "2026-05-25", "2026-05-26"]:
            insert_snapshot(
                conn,
                asin="B0GY7T45YS",
                captured_at=f"{date}T04:00:00+00:00",
                capture_date=date,
                category_id="books",
                category_name="Books",
                rank=100,
            )
        rows = query_snapshots(conn, "B0GY7T45YS")
        dates = [row["capture_date"] for row in rows]
        assert dates == ["2026-05-25", "2026-05-26", "2026-05-27"]


class TestFailures:
    def test_insert_failure(self, conn):
        insert_failure(
            conn,
            asin="B0GY7T45YS",
            attempted_at="2026-05-25T04:00:00+00:00",
            reason="captcha",
            detail="missing_bsr_block",
        )
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM failures").fetchall()
        assert len(rows) == 1
        assert rows[0]["reason"] == "captcha"
