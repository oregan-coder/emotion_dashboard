"""Bootstrap the narrow 883900 series from the authenticated historical API."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from collection import fuyao_provider

from . import storage
from .common import CODE, SERIES, connect, database, day, dumps, now_iso
from .index_source import normalize


CALENDAR_KEY = "m8839_calendar_fuyou_v1"


def _calendar_days(project: Path) -> list[str]:
    cache = project / "data" / "trading_calendar_cache.json"
    try:
        values = json.loads(cache.read_text(encoding="utf-8")).get("days") or []
    except (OSError, ValueError, TypeError):
        values = []
    return sorted({value for item in values if (value := day(item))})


def build_bundle(calendar: list[str], start: str, end: str, *, fetch=fuyao_provider.historical_883900_range) -> dict:
    """Fetch and validate one continuous source range against verified sessions."""
    calendar = sorted({value for item in calendar if (value := day(item))})
    start, end = day(start), day(end)
    if not start or not end or start > end or start not in calendar or end not in calendar:
        raise ValueError("883900同步日期不在已核验交易日历中")
    start_index, end_index = calendar.index(start), calendar.index(end)
    if start_index == 0:
        raise ValueError("883900首个目标日缺少前一交易日收盘")
    query_start = calendar[start_index - 1]
    expected = calendar[start_index - 1:end_index + 1]
    payload, receipt, raw_text = fetch(query_start, end)
    rows = payload.get("item") or []
    source_rows = []
    observed = set()
    for row in rows:
        trade_date = fuyao_provider.datetime.fromtimestamp(row["date_ms"] / 1000, fuyao_provider.SHANGHAI).strftime("%Y%m%d")
        if trade_date in expected:
            observed.add(trade_date)
            source_rows.append({"date": trade_date, "close": row["close_price"]})
    missing = [trade_date for trade_date in expected if trade_date not in observed]
    if missing:
        raise ValueError("883900历史响应缺少交易日：" + ",".join(missing))
    bundle = normalize(
        {"code": "883900.TI", "name": "昨日涨停", "rows": source_rows,
         "identity_proof": {"thscode": payload.get("thscode"), "interval": payload.get("interval")}},
        calendar, query_start, end, raw_text, "FUYAO_883900_HISTORICAL", receipt["url"],
    )
    bundle["response"]["metadata"].update({"receipt": receipt, "calendar_source": "FUYAO_TRADING_DAYS_CACHE",
                                               "expected_dates": expected})
    return bundle


def sync_for_date(project, end: str, *, calendar=None, start=None) -> dict:
    """Persist the target's five-session window and activate only after readback."""
    project = Path(project).resolve()
    db = database(project)
    calendar = calendar or _calendar_days(project)
    end = day(end)
    if not end or end not in calendar:
        return {"status": "CALENDAR_DATE_MISSING", "activated": storage.active(db), "writes_daily": False}
    end_index = calendar.index(end)
    start = day(start) or calendar[max(0, end_index - 4)]
    run_id, started = uuid.uuid4().hex, time.time()
    try:
        storage.install_schema(db)
        bundle = build_bundle(calendar, start, end)
        saved = storage.save_index(db, bundle, activate=False)
        with connect(db, True, timeout=5) as conn:
            conn.execute("INSERT INTO m8839_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         (CALENDAR_KEY, dumps({"status": "VALID", "verified": True, "dates": calendar,
                                               "source": "FUYAO_TRADING_DAYS_CACHE", "updated_at": now_iso()})))
            conn.commit()
        from .money_view import make_view
        view = make_view(calendar, storage.daily_rows(db), end, start)
        if (view.get("current") or {}).get("status") != "VALID":
            return {"status": "WINDOW_NOT_READY", "activated": storage.active(db), "writes_daily": bool(saved["new_or_revised_days"]),
                    "current": view.get("current"), "coverage": view.get("history_coverage")}
        storage.set_active(db, True)
        result = {"status": "COMPLETE", "activated": True, "writes_daily": bool(saved["new_or_revised_days"]),
                  "new_days": saved["new_or_revised_days"], "range": [start, end],
                  "current": view["current"], "coverage": view["history_coverage"], "source": SERIES}
        storage.save_run(db, run_id, "883900_fuyou_bootstrap", started, "COMPLETE", result)
        return result
    except Exception as exc:
        result = {"status": "ERROR", "activated": storage.active(db), "writes_daily": False,
                  "error_type": type(exc).__name__, "error": str(exc)[:500]}
        try:
            storage.save_run(db, run_id, "883900_fuyou_bootstrap", started, "ERROR", result)
        except Exception:
            pass
        return result
