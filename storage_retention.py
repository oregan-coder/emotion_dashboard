"""Bounded storage controls for the operational and evidence SQLite databases."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


WARN_BYTES = 1 * 1024 * 1024
LIMIT_BYTES = 3 * 1024 * 1024
BATCH_COLUMNS = {
    "batch_id", "base_batch_id", "source_batch_id", "t_batch_id", "observed_batch_id",
}


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _tables(conn: sqlite3.Connection) -> list[str]:
    return [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )]


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({_quote(table)})")}


def _evidence_path(hot: Path) -> Path:
    marker = Path(str(hot) + ".evidence_path")
    if not marker.is_file():
        raise FileNotFoundError(f"EVIDENCE_PATH_MARKER_MISSING:{marker}")
    evidence = Path(marker.read_text(encoding="utf-8").strip())
    if not evidence.is_file():
        raise FileNotFoundError(f"EVIDENCE_DATABASE_MISSING:{evidence}")
    return evidence


def _evidence_totals(path: Path) -> tuple[int, int]:
    with closing(sqlite3.connect(path, timeout=30)) as conn:
        count, size = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(zlib_len), 0) FROM ev_blob"
        ).fetchone()
    return int(count), int(size)


def bootstrap(hot_path: str | Path) -> dict:
    """Install only the small control tables required by an otherwise empty database."""
    hot = Path(hot_path)
    with closing(sqlite3.connect(hot, timeout=30)) as conn:
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS storage_ledger(
                batch_id TEXT PRIMARY KEY,
                trade_date TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                evidence_blobs_before INTEGER NOT NULL,
                evidence_blobs_added INTEGER NOT NULL,
                evidence_bytes_added INTEGER NOT NULL,
                hot_bytes_after INTEGER NOT NULL,
                daily_evidence_bytes INTEGER NOT NULL,
                budget_status TEXT NOT NULL
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_storage_ledger_trade_date "
            "ON storage_ledger(trade_date, recorded_at)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO meta(key,value) VALUES(?,?)",
            ("storage_retention", "5535_STORAGE_RETENTION_V1"),
        )
        conn.commit()
        # Configure incremental page reclamation once while the database is empty.
        if conn.execute("PRAGMA auto_vacuum").fetchone()[0] == 0:
            conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
            conn.execute("VACUUM")
    return {"hot": str(hot), "evidence": str(_evidence_path(hot))}


def begin_capture(hot_path: str | Path) -> dict:
    hot = Path(hot_path)
    bootstrap(hot)
    count, size = _evidence_totals(_evidence_path(hot))
    return {"evidence_blob_count": count, "evidence_bytes": size}


def _batch_table(conn: sqlite3.Connection) -> str:
    tables = set(_tables(conn))
    if "batches_fact" in tables:
        return "batches_fact"
    if "batches" in tables:
        return "batches"
    raise RuntimeError("BATCH_TABLE_MISSING")


def _keep_latest_two(conn: sqlite3.Connection, batch_table: str, trade_date: str) -> list[str]:
    columns = _columns(conn, batch_table)
    if not {"id", "trade_date", "stored_at"} <= columns:
        raise RuntimeError(f"BATCH_TABLE_COLUMNS_MISSING:{batch_table}")
    return [row[0] for row in conn.execute(
        f"SELECT id FROM {_quote(batch_table)} WHERE trade_date=? "
        "ORDER BY stored_at DESC, id DESC LIMIT 2",
        (trade_date,),
    )]


def _batch_ids_to_remove(conn: sqlite3.Connection, batch_table: str, trade_date: str) -> list[str]:
    keep = _keep_latest_two(conn, batch_table, trade_date)
    placeholders = ",".join("?" * len(keep))
    sql = f"SELECT id FROM {_quote(batch_table)} WHERE trade_date=?"
    params: list[str] = [trade_date]
    if keep:
        sql += f" AND id NOT IN ({placeholders})"
        params.extend(keep)
    return [row[0] for row in conn.execute(sql, params)]


def _delete_batch_dependents(conn: sqlite3.Connection, batch_ids: list[str]) -> dict[str, int]:
    if not batch_ids:
        return {}
    placeholders = ",".join("?" * len(batch_ids))
    deleted: dict[str, int] = {}
    for table in _tables(conn):
        if table in {"batch_dim", "master_member", "master_member_alias"}:
            continue
        columns = _columns(conn, table)
        matches = sorted(columns & BATCH_COLUMNS)
        if not matches:
            continue
        predicates = " OR ".join(f"{_quote(column)} IN ({placeholders})" for column in matches)
        params = batch_ids * len(matches)
        count = conn.execute(f"DELETE FROM {_quote(table)} WHERE {predicates}", params).rowcount
        if count:
            deleted[table] = count
    return deleted


def _delete_master_batch_members(conn: sqlite3.Connection, batch_ids: list[str]) -> int:
    """Remove aliases/members for discarded batches without breaking kept aliases."""
    required = {"batch_dim", "master_member", "master_member_alias"}
    if not required <= set(_tables(conn)) or not batch_ids:
        return 0
    placeholders = ",".join("?" * len(batch_ids))
    obsolete = [row[0] for row in conn.execute(
        f"SELECT batch_int FROM batch_dim WHERE batch_id IN ({placeholders})", batch_ids
    )]
    if not obsolete:
        return 0
    obsolete_set = set(obsolete)
    # A kept alias may still point to a discarded canonical payload. Materialize one
    # kept alias first, then repoint all kept aliases before deleting the old rows.
    for canonical in obsolete:
        dependents = [row[0] for row in conn.execute(
            "SELECT batch_int FROM master_member_alias WHERE canonical_batch_int=?", (canonical,)
        ) if row[0] not in obsolete_set]
        if not dependents:
            continue
        replacement = dependents[0]
        conn.execute(
            "INSERT OR IGNORE INTO master_member(batch_int,frame,code,blob_id) "
            "SELECT ?,frame,code,blob_id FROM master_member WHERE batch_int=?",
            (replacement, canonical),
        )
        conn.execute(
            "UPDATE master_member_alias SET canonical_batch_int=? WHERE canonical_batch_int=?",
            (replacement, canonical),
        )
    obsolete_marks = ",".join("?" * len(obsolete))
    deleted = conn.execute(
        f"DELETE FROM master_member_alias WHERE batch_int IN ({obsolete_marks})", obsolete
    ).rowcount
    deleted += conn.execute(
        f"DELETE FROM master_member WHERE batch_int IN ({obsolete_marks})", obsolete
    ).rowcount
    conn.execute(f"DELETE FROM batch_dim WHERE batch_int IN ({obsolete_marks})", obsolete)
    return deleted


def _collect_blob_ids(conn: sqlite3.Connection) -> set[int]:
    blob_ids: set[int] = set()
    for table in _tables(conn):
        for column in _columns(conn, table):
            if "blob" not in column.lower():
                continue
            for (blob_id,) in conn.execute(
                f"SELECT {_quote(column)} FROM {_quote(table)} WHERE {_quote(column)} IS NOT NULL"
            ):
                try:
                    blob_ids.add(int(blob_id))
                except (TypeError, ValueError):
                    pass
    return blob_ids


def _delete_orphan_blobs(evidence: Path, referenced: set[int]) -> int:
    with closing(sqlite3.connect(evidence, timeout=30)) as conn:
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("BEGIN IMMEDIATE")
        all_ids = [row[0] for row in conn.execute("SELECT blob_id FROM ev_blob")]
        orphans = [blob_id for blob_id in all_ids if blob_id not in referenced]
        for offset in range(0, len(orphans), 900):
            chunk = orphans[offset:offset + 900]
            conn.execute(
                "DELETE FROM ev_blob WHERE blob_id IN (" + ",".join("?" * len(chunk)) + ")",
                chunk,
            )
        conn.commit()
    return len(orphans)


def retain_latest_two(hot_path: str | Path, trade_date: str) -> dict:
    """Keep the two newest stored batches for one date, then reclaim unreachable evidence."""
    hot = Path(hot_path)
    evidence = _evidence_path(hot)
    with closing(sqlite3.connect(hot, timeout=30)) as conn:
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("BEGIN IMMEDIATE")
        batch_table = _batch_table(conn)
        keep = _keep_latest_two(conn, batch_table, trade_date)
        remove = _batch_ids_to_remove(conn, batch_table, trade_date)
        deleted = _delete_batch_dependents(conn, remove)
        master_deleted = _delete_master_batch_members(conn, remove)
        if master_deleted:
            deleted["master_member"] = master_deleted
        if remove:
            conn.execute(
                f"DELETE FROM {_quote(batch_table)} WHERE id IN ({','.join('?' * len(remove))})",
                remove,
            )
        # published_days must never refer to a removed first_batch_id.
        if "published_days" in _tables(conn) and keep:
            published_columns = _columns(conn, "published_days")
            if {"trade_date", "batch_id", "first_batch_id"} <= published_columns:
                conn.execute(
                    "UPDATE published_days SET first_batch_id=? WHERE trade_date=? "
                    "AND first_batch_id NOT IN (" + ",".join("?" * len(keep)) + ")",
                    [keep[-1], trade_date, *keep],
                )
        referenced = _collect_blob_ids(conn)
        conn.commit()
    orphan_count = _delete_orphan_blobs(evidence, referenced)
    with closing(sqlite3.connect(hot, timeout=30)) as conn:
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA incremental_vacuum(100000)")
    return {"trade_date": trade_date, "kept_batch_ids": keep, "removed_batch_ids": remove,
            "deleted_rows": deleted, "orphan_blobs_deleted": orphan_count}


def complete_capture(hot_path: str | Path, trade_date: str, batch_id: str, before: dict) -> dict:
    """Write one measurement row and enforce the two-batch retention rule after publication."""
    hot = Path(hot_path)
    bootstrap(hot)
    retention = retain_latest_two(hot, trade_date)
    after_count, after_bytes = _evidence_totals(_evidence_path(hot))
    added_bytes = max(0, after_bytes - int(before["evidence_bytes"]))
    added_count = max(0, after_count - int(before["evidence_blob_count"]))
    with closing(sqlite3.connect(hot, timeout=30)) as conn:
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("BEGIN IMMEDIATE")
        daily_before = conn.execute(
            "SELECT COALESCE(SUM(evidence_bytes_added), 0) FROM storage_ledger WHERE trade_date=?",
            (trade_date,),
        ).fetchone()[0]
        daily_total = int(daily_before) + added_bytes
        status = "OK" if daily_total <= WARN_BYTES else "WARN" if daily_total <= LIMIT_BYTES else "OVER_BUDGET"
        conn.execute(
            """INSERT OR REPLACE INTO storage_ledger(
                batch_id,trade_date,recorded_at,evidence_blobs_before,evidence_blobs_added,
                evidence_bytes_added,hot_bytes_after,daily_evidence_bytes,budget_status
            ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (batch_id, trade_date, datetime.now(timezone.utc).isoformat(),
             int(before["evidence_blob_count"]), added_count, added_bytes,
             hot.stat().st_size, daily_total, status),
        )
        conn.commit()
    return {"batch_id": batch_id, "evidence_bytes_added": added_bytes,
            "evidence_blobs_added": added_count, "daily_evidence_bytes": daily_total,
            "budget_status": status, "retention": retention}
