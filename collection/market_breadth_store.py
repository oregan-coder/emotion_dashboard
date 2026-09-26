"""Small, dated market-breadth fact store.

The provider response remains evidence; this table keeps only the validated
aggregate needed by the dashboard and score readers.  It deliberately has no
stock-level rows and never fills missing counts with zero.
"""
from __future__ import annotations

import csv
import hashlib
import math
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


def _import_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS market_breadth_imports(
            source_batch_id TEXT PRIMARY KEY,
            source_file TEXT NOT NULL,
            file_sha256 TEXT NOT NULL,
            source_rows INTEGER NOT NULL,
            imported_days INTEGER NOT NULL,
            skipped_dates_json TEXT NOT NULL,
            imported_at TEXT NOT NULL
        )"""
    )


def _number(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def summarize_daily_k_rows(rows) -> tuple[list[dict], int, list[str]]:
    """Aggregate full-market daily-K rows without retaining stock-level data."""
    daily: dict[str, dict] = {}
    source_rows = 0
    for row in rows:
        source_rows += 1
        date = _day(row.get("date"))
        code = str(row.get("thscode") or "").strip()
        if not date or not code:
            raise ValueError("日线文件存在无效 date 或 thscode")
        bucket = daily.setdefault(date, {"codes": set(), "up": 0, "down": 0, "flat": 0, "unknown": 0})
        if code in bucket["codes"]:
            raise ValueError(f"日线文件存在重复日期证券：{date}/{code}")
        bucket["codes"].add(code)
        change = _number(row.get("pct_change"))
        if change is None:
            bucket["unknown"] += 1
        elif change > 0:
            bucket["up"] += 1
        elif change < 0:
            bucket["down"] += 1
        else:
            bucket["flat"] += 1

    records, skipped_dates = [], []
    for date, bucket in sorted(daily.items()):
        if not (bucket["up"] + bucket["down"] + bucket["flat"]):
            skipped_dates.append(date)
            continue
        records.append({
            "trade_date": date,
            "up": bucket["up"], "down": bucket["down"],
            "flat": bucket["flat"], "unknown": bucket["unknown"],
            "total": len(bucket["codes"]),
        })
    return records, source_rows, skipped_dates


def import_daily_k_csv(db_path: Path, csv_path: Path) -> dict:
    """Validate and atomically import daily-K-derived breadth aggregates."""
    csv_path = Path(csv_path).resolve()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {"date", "thscode", "pct_change"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("日线文件必须包含 date、thscode、pct_change 列")
        records, source_rows, skipped_dates = summarize_daily_k_rows(reader)
    if not records:
        raise ValueError("日线文件没有可计算市场广度的交易日")

    digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    source_batch_id = "LOCAL_DAILY_K_" + digest[:16]
    imported_at = datetime.now(timezone.utc).isoformat()
    source_as_of = datetime.fromtimestamp(csv_path.stat().st_mtime, timezone.utc).isoformat()
    conn = sqlite3.connect(str(db_path), timeout=10)
    try:
        ensure_schema(conn)
        _import_schema(conn)
        for record in records:
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
                (record["trade_date"], record["up"], record["down"], record["flat"], record["unknown"],
                 "VALID", "HITHINK_LOCAL_A_SHARE_DAILY_K", record["trade_date"], source_as_of,
                 source_batch_id, SCHEMA_VERSION, imported_at),
            )
        conn.execute(
            """INSERT INTO market_breadth_imports(
                source_batch_id,source_file,file_sha256,source_rows,imported_days,
                skipped_dates_json,imported_at
            ) VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(source_batch_id) DO UPDATE SET imported_at=excluded.imported_at""",
            (source_batch_id, str(csv_path), digest, source_rows, len(records),
             ",".join(skipped_dates), imported_at),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {
        "source_batch_id": source_batch_id,
        "file_sha256": digest,
        "source_rows": source_rows,
        "imported_days": len(records),
        "first_trade_date": records[0]["trade_date"],
        "last_trade_date": records[-1]["trade_date"],
        "skipped_dates": skipped_dates,
    }


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
                -- A replay may re-save an imported local aggregate without
                -- carrying the import id.  Retain that immutable CSV lineage
                -- instead of making a previously verifiable fact unverifiable.
                source_batch_id=CASE
                    WHEN excluded.source='HITHINK_LOCAL_A_SHARE_DAILY_K'
                         AND excluded.source_batch_id IS NULL
                    THEN market_breadth_daily.source_batch_id
                    ELSE excluded.source_batch_id
                END,
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


def read_import(db_path: Path, source_batch_id: str) -> dict | None:
    if not source_batch_id or not db_path.is_file():
        return None
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        try:
            row = conn.execute(
                "SELECT source_batch_id,source_file,file_sha256,source_rows,imported_days,"
                "skipped_dates_json,imported_at FROM market_breadth_imports WHERE source_batch_id=?",
                (source_batch_id,),
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
