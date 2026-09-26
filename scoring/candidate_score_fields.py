"""Minimal, verified supplemental fields for two-board research cards.

Fuyao's historical limit-up pool is the canonical candidate list, but it does
not currently expose turnover, amount, or open-break count.  This module makes
one supplementary historical pool request and fills only absent fields after a
same-date, same-code, same-close and same-board match.  It never changes the
candidate list, price, seal data, or any non-matching row.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
import math
import re
import json
from pathlib import Path

import pandas as pd


CN = timezone(timedelta(hours=8))
METHOD = "EASTMONEY_LIMIT_UP_POOL_SAME_DATE_EXACT_CLOSE_V1"
_FIELDS = ("成交额", "换手率", "炸板次数")


def _cached_previous_limit_up_pool(date):
    """Load a previously captured EastMoney same-day pool, if it exists."""
    path = (Path(__file__).resolve().parent / "data" / "history_metric_request_cache_v2"
            / f"stock_zt_pool_previous_em_{date}.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        frame = payload.get("frame") or {}
        columns, rows = frame.get("columns"), frame.get("data")
        if not isinstance(columns, list) or not isinstance(rows, list):
            return None
        return pd.DataFrame(rows, columns=columns)
    except (OSError, ValueError, TypeError):
        return None


def _code(value):
    value = re.sub(r"^(?:sh|sz|bj)", "", str(value or ""), flags=re.I)
    return value if re.fullmatch(r"\d{6}", value) else None


def _number(value, *, minimum=None, allow_zero=True):
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result) or (not allow_zero and result == 0):
        return None
    if minimum is not None and result < minimum:
        return None
    return result


def _same_close(left, right):
    try:
        a, b = Decimal(str(left)), Decimal(str(right))
        return a.is_finite() and b.is_finite() and a > 0 and b > 0 and a == b
    except (InvalidOperation, ValueError, TypeError):
        return False


def _default_fetch(date):
    import akshare as ak
    return ak.stock_zt_pool_em(date=date)


def enrich_limit_up_score_fields(frame, date, *, fetch=None):
    """Fill missing candidate score fields in-place and return compact evidence.

    ``fetch`` exists for deterministic tests.  An unsuccessful or incomplete
    supplement leaves the canonical Fuyao frame untouched and visible as such.
    """
    evidence = {
        "method": METHOD,
        "requested_date": str(date),
        "status": "DATA_PENDING",
        "matched_codes": [],
        "unmatched_codes": [],
        "field_sources": {},
    }
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        evidence["status"] = "NO_LIMIT_UP_ROWS"
        return evidence

    def finish():
        evidence["retrieved_at"] = datetime.now(CN).isoformat()
        frame.attrs["candidate_score_field_evidence"] = evidence
        return evidence

    required = {"代码", "连板数", "最新价"}
    if not required.issubset(frame.columns):
        evidence.update(status="CANONICAL_COLUMNS_MISSING", missing_columns=sorted(required-set(frame.columns)))
        return finish()
    candidates = {}
    for index, row in frame.iterrows():
        code = _code(row.get("代码"))
        if code and _number(row.get("连板数"), minimum=2) == 2:
            candidates[code] = index
    if not candidates:
        evidence["status"] = "NO_TWO_BOARD_CANDIDATES"
        return finish()
    try:
        source = (fetch or _default_fetch)(str(date))
    except Exception as exc:
        evidence.update(status="REQUEST_ERROR", error_type=type(exc).__name__, error=str(exc))
        return finish()
    if not isinstance(source, pd.DataFrame) or source.empty:
        # EastMoney only retains a short historical window.  The user-approved
        # fallback is deliberately recorded separately from API-derived values.
        if "炸板次数" not in frame.columns:
            frame["炸板次数"] = None
        defaults = {}
        for code, index in candidates.items():
            if pd.isna(frame.at[index, "炸板次数"]):
                frame.at[index, "炸板次数"] = 1
                defaults[code] = {
                    "source": "USER_APPROVED_DEFAULT_WHEN_EASTMONEY_HISTORY_EMPTY",
                    "fields": ["炸板次数"],
                    "value": 1,
                    "reason": "EASTMONEY_LIMIT_UP_POOL_EMPTY_RESPONSE",
                }
        if defaults:
            evidence["defaulted_fields"] = defaults

        cached = _cached_previous_limit_up_pool(str(date))
        if not isinstance(cached, pd.DataFrame) or cached.empty:
            evidence.update(
                status="EMPTY_RESPONSE_WITH_USER_DEFAULT_OPEN_BREAK",
                primary_source_status="EMPTY_RESPONSE",
            )
            return finish()
        cache_required = {"代码", "昨日连板数", "最新价", "成交额", "换手率"}
        missing = cache_required - set(cached.columns)
        if missing:
            evidence.update(status="EMPTY_RESPONSE_CACHE_COLUMNS_MISSING", missing_columns=sorted(missing))
            return finish()
        cached_by_code = {_code(row.get("代码")): row for _, row in cached.iterrows() if _code(row.get("代码"))}
        for code, index in candidates.items():
            row = cached_by_code.get(code)
            canonical = frame.loc[index]
            if (row is None or _number(row.get("昨日连板数"), minimum=1) != 1
                    or not _same_close(canonical.get("最新价"), row.get("最新价"))):
                evidence["unmatched_codes"].append(code)
                continue
            written = []
            for field in ("成交额", "换手率"):
                if field not in frame.columns:
                    frame[field] = None
                if pd.notna(canonical.get(field)):
                    continue
                value = _number(row.get(field), minimum=0, allow_zero=field == "换手率")
                if value is not None:
                    frame.at[index, field] = value
                    written.append(field)
            if written:
                evidence["field_sources"][code] = {
                    "fields": written, "source": "EASTMONEY_PREVIOUS_LIMIT_UP_CACHE",
                    "close_verified": True, "previous_board_verified": True,
                }
        evidence.update(
            status="PARTIAL_VERIFIED_FIELDS_WITH_USER_DEFAULT_OPEN_BREAK",
            primary_source_status="EMPTY_RESPONSE",
        )
        return finish()
    missing = {"代码", "连板数", "最新价", "成交额", "换手率", "炸板次数"} - set(source.columns)
    if missing:
        evidence.update(status="SOURCE_COLUMNS_MISSING", missing_columns=sorted(missing))
        return finish()
    source_by_code = {}
    for _, row in source.iterrows():
        code = _code(row.get("代码"))
        if code and code not in source_by_code:
            source_by_code[code] = row
    for code, index in candidates.items():
        row = source_by_code.get(code)
        canonical = frame.loc[index]
        if row is None or _number(row.get("连板数"), minimum=2) != 2 or not _same_close(canonical.get("最新价"), row.get("最新价")):
            evidence["unmatched_codes"].append(code)
            continue
        written = []
        for field in _FIELDS:
            if field not in frame.columns:
                frame[field] = None
            if pd.notna(canonical.get(field)):
                continue
            value = row.get(field)
            if field == "炸板次数":
                value = _number(value, minimum=0)
                if value is not None and value.is_integer():
                    value = int(value)
            elif field in ("成交额", "换手率"):
                value = _number(value, minimum=0, allow_zero=field == "换手率")
            if value is not None:
                frame.at[index, field] = value
                written.append(field)
        if {"成交额", "换手率", "炸板次数"}.issubset(set(written) | {f for f in _FIELDS if pd.notna(canonical.get(f))}):
            evidence["matched_codes"].append(code)
            evidence["field_sources"][code] = {"fields": written, "source": "EASTMONEY", "close_verified": True}
        else:
            evidence["unmatched_codes"].append(code)
    evidence["status"] = "VALID" if evidence["matched_codes"] else "NO_VERIFIED_CANDIDATE_MATCH"
    return finish()
