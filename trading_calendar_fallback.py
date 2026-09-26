"""Conservative local fallback for the dashboard trading calendar.

The normal Sina calendar remains authoritative.  This fallback is only used
when that request is unavailable: persisted verified calendar dates are reused
first, then a date is admitted only when the existing limit-up-pool provider
returns actual rows for that exact date.  It never turns a weekday into a
trading day and deliberately leaves zero-limit-up sessions unresolved.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _day(value):
    return str(value or "").replace("-", "")


def _persisted_dates(database: Path, end_date: str) -> set[str]:
    if not database.is_file():
        return set()
    try:
        with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as conn:
            row = conn.execute(
                "SELECT r.payload_json FROM p50_heads h JOIN p50_revisions r "
                "ON r.id=h.revision_id WHERE h.kind='calendar' AND h.key='CN_A'"
            ).fetchone()
            days = set(_day(item) for item in json.loads(row[0]).get("days", []) if _day(item)) if row else set()
            row = conn.execute("SELECT value FROM m8839_meta WHERE key='tail_calendar_r1'").fetchone()
            if row:
                days.update(_day(item) for item in json.loads(row[0]).get("days", []) if _day(item))
            return {item for item in days if item <= end_date}
    except (sqlite3.Error, TypeError, ValueError, json.JSONDecodeError):
        return set()


def install(project_dir, data_fetcher):
    """Install once.  Existing normal calendar behaviour is unchanged."""
    if getattr(data_fetcher.get_trade_dates, "_5535_verified_fallback", False):
        return
    original = data_fetcher.get_trade_dates
    original_latest = data_fetcher.latest_trade_date
    database = Path(project_dir) / "data" / ".migration_shadow" / "market_store_5535.next.sqlite3"

    def get_trade_dates(end_date, count=2):
        try:
            return original(end_date, count)
        except RuntimeError as original_error:
            end = _day(end_date)
            try:
                cursor = datetime.strptime(end, "%Y%m%d")
            except ValueError:
                raise original_error
            candidates = _persisted_dates(database, end)
            # Only bridge the uncovered tail. A non-empty exact-date pool is
            # provider evidence that this candidate is an actual session.
            for _ in range(16):
                candidate = cursor.strftime("%Y%m%d")
                if candidate not in candidates:
                    try:
                        pool = data_fetcher._limit_up_pool(candidate)
                        if len(pool) and not pool.attrs.get("fetch_error"):
                            candidates.add(candidate)
                    except Exception:
                        pass
                cursor -= timedelta(days=1)
            resolved = sorted(candidates)
            if len(resolved) < count or end not in candidates:
                raise original_error
            return resolved[-count:]

    get_trade_dates._5535_verified_fallback = True
    data_fetcher.get_trade_dates = get_trade_dates

    def latest_trade_date():
        # A daily snapshot is a closing fact. Before close, "latest" means the
        # latest completed session, never the still-changing intraday session.
        now = datetime.now(timezone(timedelta(hours=8)))
        end = now.strftime("%Y%m%d") if (now.hour, now.minute) >= (15, 30) else (now - timedelta(days=1)).strftime("%Y%m%d")
        try:
            return data_fetcher.get_trade_dates(end, 1)[0]
        except RuntimeError:
            return original_latest()

    data_fetcher.latest_trade_date = latest_trade_date
