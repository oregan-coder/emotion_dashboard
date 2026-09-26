from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage_retention import begin_capture, complete_capture, retain_latest_two


def test_same_day_keeps_two_newest_batches_and_reclaims_old_evidence(tmp_path):
    hot = tmp_path / "hot.sqlite3"
    evidence = tmp_path / "evidence.sqlite3"
    Path(str(hot) + ".evidence_path").write_text(str(evidence), encoding="utf-8")
    with sqlite3.connect(evidence) as conn:
        conn.execute("CREATE TABLE ev_blob(blob_id INTEGER PRIMARY KEY, zlib_len INTEGER NOT NULL)")
        conn.executemany("INSERT INTO ev_blob VALUES(?,?)", [(1, 10), (2, 10), (3, 10)])
    with sqlite3.connect(hot) as conn:
        conn.executescript("""
            CREATE TABLE batches_fact(id TEXT PRIMARY KEY, trade_date TEXT, stored_at TEXT);
            CREATE TABLE published_days(trade_date TEXT PRIMARY KEY, batch_id TEXT, first_batch_id TEXT);
            CREATE TABLE source_rows_fact(batch_id TEXT, blob_id INTEGER);
            CREATE TABLE s02b_revisions(base_batch_id TEXT, blob_id INTEGER);
            CREATE TABLE batch_dim(batch_int INTEGER PRIMARY KEY, batch_id TEXT);
            CREATE TABLE master_member(batch_int INTEGER, frame TEXT, code TEXT, blob_id INTEGER);
            CREATE TABLE master_member_alias(batch_int INTEGER PRIMARY KEY, canonical_batch_int INTEGER);
        """)
        conn.executemany("INSERT INTO batches_fact VALUES(?,?,?)", [
            ("B1", "20260925", "2026-09-25T09:00:00+00:00"),
            ("B2", "20260925", "2026-09-25T10:00:00+00:00"),
            ("B3", "20260925", "2026-09-25T11:00:00+00:00"),
        ])
        conn.execute("INSERT INTO published_days VALUES('20260925','B3','B1')")
        conn.executemany("INSERT INTO source_rows_fact VALUES(?,?)", [("B1", 1), ("B2", 2), ("B3", 3)])
        conn.execute("INSERT INTO s02b_revisions VALUES('B1',1)")
        conn.executemany("INSERT INTO batch_dim VALUES(?,?)", [(1, "B1"), (2, "B2"), (3, "B3")])
        conn.executemany("INSERT INTO master_member VALUES(?,?,?,?)", [(1, "all", "000001", 1), (2, "all", "000001", 2), (3, "all", "000001", 3)])
        conn.executemany("INSERT INTO master_member_alias VALUES(?,?)", [(1, 1), (2, 2), (3, 3)])

    result = retain_latest_two(hot, "20260925")

    assert result["kept_batch_ids"] == ["B3", "B2"]
    assert result["removed_batch_ids"] == ["B1"]
    assert result["orphan_blobs_deleted"] == 1
    with sqlite3.connect(hot) as conn:
        assert [row[0] for row in conn.execute("SELECT id FROM batches_fact ORDER BY id")] == ["B2", "B3"]
        assert conn.execute("SELECT first_batch_id FROM published_days").fetchone()[0] == "B2"
        assert conn.execute("SELECT COUNT(*) FROM source_rows_fact WHERE batch_id='B1'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM master_member WHERE batch_int=1").fetchone()[0] == 0
    with sqlite3.connect(evidence) as conn:
        assert [row[0] for row in conn.execute("SELECT blob_id FROM ev_blob ORDER BY blob_id")] == [2, 3]


def test_capture_ledger_records_new_compressed_evidence(tmp_path):
    hot = tmp_path / "hot.sqlite3"
    evidence = tmp_path / "evidence.sqlite3"
    Path(str(hot) + ".evidence_path").write_text(str(evidence), encoding="utf-8")
    with sqlite3.connect(evidence) as conn:
        conn.execute("CREATE TABLE ev_blob(blob_id INTEGER PRIMARY KEY, zlib_len INTEGER NOT NULL)")
    with sqlite3.connect(hot) as conn:
        conn.executescript("""
            CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE batches_fact(id TEXT PRIMARY KEY, trade_date TEXT, stored_at TEXT);
            CREATE TABLE published_days(trade_date TEXT PRIMARY KEY, batch_id TEXT, first_batch_id TEXT);
            CREATE TABLE source_rows_fact(batch_id TEXT, blob_id INTEGER);
        """)

    before = begin_capture(hot)
    with sqlite3.connect(hot) as conn:
        conn.execute("INSERT INTO batches_fact VALUES('B1','20260925','2026-09-25T09:00:00+00:00')")
        conn.execute("INSERT INTO published_days VALUES('20260925','B1','B1')")
        conn.execute("INSERT INTO source_rows_fact VALUES('B1',1)")
    with sqlite3.connect(evidence) as conn:
        conn.execute("INSERT INTO ev_blob VALUES(1, 2097152)")

    result = complete_capture(hot, "20260925", "B1", before)

    assert result["evidence_bytes_added"] == 2097152
    assert result["daily_evidence_bytes"] == 2097152
    assert result["budget_status"] == "WARN"
    with sqlite3.connect(hot) as conn:
        assert conn.execute(
            "SELECT budget_status FROM storage_ledger WHERE batch_id='B1'"
        ).fetchone()[0] == "WARN"
