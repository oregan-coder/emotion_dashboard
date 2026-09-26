"""Small, dated market-breadth fact store.

The provider response remains evidence; this table keeps only the validated
aggregate needed by the dashboard and score readers.  It deliberately has no
stock-level rows and never fills missing counts with zero.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3


SCHEMA_VERSION = "5535_MARKET_BREADTH_DAILY_V1"


def _day(value):
    s = str(value or "").replace("-", "")
    return s if re.fullmatch(r"\d{8}", s) else None


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS market_breadth_daily(
            trade_date TEXT PRIMARY KEY,
            up_count INTEGER,
            down_count INTEGER,
            flat_count INTEGER,
            unknown_count INTEGER,
            status TEXT NOT NULL,
            source TEXT NOT NULL,
            source_date TEXT,
            as_of TEXT,
            source_batch_id TEXT,
            rule_version TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_breadth_status_date "
        "ON market_breadth_daily(status, trade_date)"
    )


def upsert(db_path: Path, record: dict) -> bool:
    """Persist a validated aggregate; pending/invalid records are ignored."""
    date = _day(record.get("trade_date") or record.get("requested_date"))
    if not date or str(record.get("status")) != "VALID":
        return False
    values = {}
    for key in ("up", "down", "flat", "unknown"):
        value = record.get(key, 0) if key == "unknown" else record.get(key)
        if value is None:
            return False
        try:
            value = int(value)
        except (TypeError, ValueError):
            return False
        if value < 0:
            return False
        values[key] = value
    now = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(str(db_path), timeout=10)
    try:
        ensure_schema(conn)
        conn.execute(
            """INSERT INTO market_breadth_daily(
                trade_date,up_count,down_count,flat_count,unknown_count,status,
                source,source_date,as_of,source_batch_id,rule_version,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(trade_date) DO UPDATE SET
                up_count=excluded.up_count, down_count=excluded.down_count,
                flat_count=excluded.flat_count, unknown_count=excluded.unknown_count,
                status=excluded.status, source=excluded.source,
                source_date=excluded.source_date, as_of=excluded.as_of,
                source_batch_id=excluded.source_batch_id,
                rule_version=excluded.rule_version, updated_at=excluded.updated_at""",
            (date, values["up"], values["down"], values["flat"], values["unknown"],
             "VALID", str(record.get("source") or "UNKNOWN"),
             _day(record.get("source_date")), record.get("as_of"),
             record.get("source_batch_id"), SCHEMA_VERSION, now),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def read(db_path: Path, trade_date: str) -> dict | None:
    date = _day(trade_date)
    if not date or not db_path.is_file():
        return None
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        try:
            row = conn.execute(
                "SELECT trade_date,up_count,down_count,flat_count,unknown_count,status,"
                "source,source_date,as_of,source_batch_id,rule_version,updated_at "
                "FROM market_breadth_daily WHERE trade_date=?", (date,)
            ).fetchone()
        except sqlite3.OperationalError:
            return None
        return dict(row) if row else None
    finally:
        conn.close()


def from_context(context: dict, *, trade_date: str, source_batch_id: str | None = None) -> dict:
    breadth = dict((context or {}).get("breadth") or {})
    return {
        "trade_date": trade_date,
        "status": breadth.get("status"),
        "up": breadth.get("up"), "down": breadth.get("down"),
        "flat": breadth.get("flat"), "unknown": breadth.get("unknown", 0),
        "source": breadth.get("source") or "LEGULEGU",
        "source_date": breadth.get("source_date") or trade_date,
        "as_of": breadth.get("as_of"),
        "source_batch_id": source_batch_id,
    }
