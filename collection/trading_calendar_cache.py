"""A股交易日历本地缓存。

同花顺 /api/a-share/calendar/trading-days 返回的是一段较长时间的交易日列表。
本模块把结果落到 data/trading_calendar_cache.json，避免每次打开日历浮窗或更新
数据都重新请求上游 API。月末最后三个交易日点"更新数据"时会强制刷新一次，
提前把下一个月的交易日拉进缓存。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

_CACHE_PATH = Path(__file__).resolve().parent / "data" / "trading_calendar_cache.json"


def _read_cache() -> list[str]:
    try:
        obj = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        days = obj.get("days") or []
        return [str(d).replace("-", "") for d in days if str(d).strip()]
    except (OSError, ValueError, AttributeError, TypeError):
        return []


def _write_cache(days: list[str]) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "days": sorted(set(days)),
        }
        _CACHE_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        log.warning("写交易日历缓存失败: %s", exc)


def read_cached_days() -> list[str]:
    """只读本地缓存，不打 API。缓存缺失返回空列表。"""
    return _read_cache()


def get_trading_days_cached() -> list[str]:
    """优先读本地缓存；缓存为空才请求同花顺 API 并落盘。"""
    days = _read_cache()
    if days:
        return days
    from collection.fuyao_provider import trading_days
    fresh = trading_days()
    if fresh:
        _write_cache(fresh)
    return fresh


def refresh_trading_days() -> list[str]:
    """强制请求同花顺 API 并写回缓存（用于月末预取下月日历）。合并旧缓存避免丢历史。"""
    from collection.fuyao_provider import trading_days
    fresh = trading_days()
    if fresh:
        merged = sorted(set(_read_cache()) | set(fresh))
        _write_cache(merged)
    return fresh


def is_tail_trading_day(today: str, days: list[str], n: int = 3) -> bool:
    """today 是否是 days 里本月最后 n 个交易日之一。"""
    today = str(today).replace("-", "")
    if len(today) != 8 or not days:
        return False
    ym = today[:6]
    month_days = sorted(d for d in days if d.startswith(ym))
    if today not in month_days:
        return False
    return today in month_days[-n:]
