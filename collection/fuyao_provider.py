"""Small, non-secret adapter for the Fuyao historical collection APIs."""
from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


BASE_URL = "https://fuyao.aicubes.cn"
SHANGHAI = ZoneInfo("Asia/Shanghai")
POOL_PATHS = {
    "limit_up": "/api/a-share/special-data/limit-up-pool",
    "limit_down": "/api/a-share/special-data/limit-down-pool",
    "open_board": "/api/a-share/special-data/limit-break-pool",
}
POOL_SORTS = {
    "limit_up": "limit_up_time",
    "limit_down": "last_limit_time",
    "open_board": "open_times",
}


class FuyaoError(RuntimeError):
    pass


def _day(value: str) -> str:
    text = "".join(ch for ch in str(value) if ch.isdigit())
    if len(text) != 8:
        raise ValueError("date must be YYYYMMDD")
    datetime.strptime(text, "%Y%m%d")
    return text


def day_ms(value: str) -> int:
    target = datetime.strptime(_day(value), "%Y%m%d").replace(tzinfo=SHANGHAI)
    return int(target.timestamp() * 1000)


def _credential_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise FuyaoError("APPDATA is unavailable; HiThink credential cannot be located")
    return Path(appdata) / "hithink-finance" / "credentials.env"


def api_key() -> str:
    value = os.environ.get("HITHINK_FINANCE_API_KEY", "").strip()
    if value:
        return value
    path = _credential_path()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            name, sep, candidate = line.partition("=")
            if sep and name.strip() == "HITHINK_FINANCE_API_KEY" and candidate.strip():
                return candidate.strip()
    except FileNotFoundError as exc:
        raise FuyaoError("HiThink credential is not configured") from exc
    raise FuyaoError("HiThink credential is empty")


def _summary(path: str, params: dict, response) -> dict:
    content = response.content or b""
    return {
        "source": "FUYAO",
        "url": BASE_URL + path,
        "params": dict(params),
        "http_status": response.status_code,
        "response_bytes": len(content),
        "response_sha256": hashlib.sha256(content).hexdigest(),
    }


def get_json(path: str, params: dict, *, session=None, timeout=20) -> tuple[dict, dict]:
    import requests

    client = session or requests.Session()
    # The endpoint itself reports code=2003/Missing X-api-key for Bearer auth.
    response = client.get(
        BASE_URL + path,
        params=params,
        headers={"X-api-key": api_key()},
        timeout=timeout,
    )
    summary = _summary(path, params, response)
    try:
        payload = response.json()
    except ValueError as exc:
        raise FuyaoError(f"non-JSON response ({response.status_code})") from exc
    if response.status_code != 200:
        raise FuyaoError(f"HTTP {response.status_code}")
    if not isinstance(payload, dict) or payload.get("code") != 0:
        code = payload.get("code") if isinstance(payload, dict) else None
        message = payload.get("message") if isinstance(payload, dict) else None
        raise FuyaoError(f"Fuyao business error: code={code}, message={message}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise FuyaoError("Fuyao success envelope has no data object")
    summary["request_id"] = payload.get("request_id")
    return data, summary


def _pool_row(item: dict, target: str) -> dict:
    return {
        "代码": item.get("ticker") or item.get("thscode"),
        "thscode": item.get("thscode"),
        "名称": item.get("name"),
        "连板数": item.get("continue_day_cnt"),
        "涨跌幅": item.get("price_change_ratio_pct"),
        "最新价": item.get("last_price"),
        "今开": item.get("open_price"),
        "涨停价": item.get("limit_up_price"),
        "跌停价": item.get("limit_down_price"),
        "首次封板时间": item.get("first_limit_time") or item.get("limit_up_time"),
        "最后封板时间": item.get("last_limit_time") or item.get("limit_up_time"),
        "封板资金": item.get("seal_money") or item.get("max_seal_money"),
        "涨停原因": item.get("limit_up_reason"),
        "换手率": item.get("turnover_ratio_pct"),
        "炸板次数": item.get("open_times"),
        "成交额": item.get("turnover"),
        "所属行业": item.get("industry_name") or item.get("industry"),
        "source_date": target,
    }


def pool_frame(kind: str, target: str, *, session=None, timeout=20) -> pd.DataFrame:
    if kind not in POOL_PATHS:
        raise ValueError(f"unknown pool kind: {kind}")
    target = _day(target)
    page, rows, requests = 1, [], []
    while True:
        params = {
            "date_ms": day_ms(target), "page": page, "size": 200,
            "sort_field": POOL_SORTS[kind], "sort_dir": "desc",
        }
        data, receipt = get_json(POOL_PATHS[kind], params, session=session, timeout=timeout)
        items = data.get("item")
        pagination = data.get("pagination")
        if not isinstance(items, list) or not isinstance(pagination, dict):
            raise FuyaoError("pool response is missing item/pagination")
        if any(not isinstance(item, dict) for item in items):
            raise FuyaoError("pool response contains a non-object row")
        rows.extend(_pool_row(item, target) for item in items)
        requests.append(receipt)
        total, pages, returned_page = pagination.get("total"), pagination.get("pages"), pagination.get("page")
        if not all(isinstance(value, int) and value >= 0 for value in (total, pages, returned_page)):
            raise FuyaoError("pool pagination is invalid")
        # 空池（当日该类股票为0）是正常情况：total=0/pages=0 时直接返回空 DataFrame，
        # 不能按"page>pages"误判成分页错乱。
        if total == 0:
            break
        if returned_page != page or page > pages:
            raise FuyaoError("pool pagination does not match requested page")
        if page >= pages:
            if len(rows) != total:
                raise FuyaoError("pool row count differs from pagination total")
            break
        page += 1
    frame = pd.DataFrame(rows)
    frame.attrs.update({
        "source_date": target,
        "as_of": datetime.now(SHANGHAI).isoformat(),
        "date_verified": True,
        "closing_verified": True,
        "complete": True,
        "source_contract": "FUYAO_DATE_MS_PAGED_POOL_V1",
        "validation_method": "code=0 + date_ms contract + complete pagination",
        "validation_evidence": {"requests": requests, "row_count": len(rows)},
    })
    return frame


def snapshot_rows(*, session=None, timeout=30) -> tuple[list[dict], dict]:
    """Return only the provider's current snapshot; it has no date parameter."""
    data, receipt = get_json(
        "/api/a-share/prices/snapshot",
        {},
        session=session,
        timeout=timeout,
    )
    items, total = data.get("item"), data.get("total")
    if not isinstance(items, list) or not isinstance(total, int) or len(items) != total:
        raise FuyaoError("snapshot row count is incomplete")
    if any(not isinstance(item, dict) for item in items):
        raise FuyaoError("snapshot contains a non-object row")
    timestamp = data.get("timestamp")
    if not isinstance(timestamp, int):
        raise FuyaoError("snapshot is missing its source timestamp")
    receipt.update({
        "source_date": datetime.fromtimestamp(timestamp / 1000, SHANGHAI).strftime("%Y%m%d"),
        "row_count": len(items), "complete": True,
    })
    return items, receipt


def trading_days(*, session=None, timeout=20) -> list[str]:
    data, _ = get_json("/api/a-share/calendar/trading-days", {}, session=session, timeout=timeout)
    items = data.get("item")
    if not isinstance(items, list):
        raise FuyaoError("trading calendar is missing item rows")
    days = []
    for item in items:
        if not isinstance(item, dict):
            raise FuyaoError("trading calendar contains a non-object row")
        days.append(_day(item.get("date")))
    if days != sorted(set(days)):
        raise FuyaoError("trading calendar is not ordered and unique")
    return days


def historical_cohort_frame(target: str, previous: str, cohort: pd.DataFrame, *, session=None, timeout=20) -> pd.DataFrame:
    """Fetch exact target-day daily bars for an already-known prior-day cohort."""
    target, previous = _day(target), _day(previous)
    if "thscode" not in cohort.columns:
        raise FuyaoError("previous limit-up pool is missing provider thscode identities")
    members = []
    for _, row in cohort.iterrows():
        thscode = row.get("thscode")
        if not isinstance(thscode, str) or not thscode.strip():
            raise FuyaoError("previous limit-up pool has an invalid thscode")
        members.append({"thscode": thscode, "代码": row.get("代码"), "名称": row.get("名称")})

    def one(member):
        data, receipt = get_json(
            "/api/a-share/prices/historical",
            {"thscode": member["thscode"], "interval": "1d", "start": day_ms(previous), "end": day_ms(target), "adjust": "none"},
            session=session,
            timeout=timeout,
        )
        rows = data.get("item")
        if not isinstance(rows, list):
            raise FuyaoError(f"{member['thscode']} history is missing item rows")
        by_day = {}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("date_ms"), int):
                raise FuyaoError(f"{member['thscode']} history has an invalid date_ms")
            observed = datetime.fromtimestamp(row["date_ms"] / 1000, SHANGHAI).strftime("%Y%m%d")
            by_day[observed] = row
        if target not in by_day or previous not in by_day:
            raise FuyaoError(f"{member['thscode']} history does not cover requested trading days")
        close, prior_close = by_day[target].get("close_price"), by_day[previous].get("close_price")
        if isinstance(close, bool) or isinstance(prior_close, bool) or not isinstance(close, (int, float)) or not isinstance(prior_close, (int, float)) or prior_close == 0:
            raise FuyaoError(f"{member['thscode']} history has an invalid close price")
        receipt.update({"thscode": member["thscode"], "requested_date": target, "previous_date": previous, "row_count": len(rows)})
        return {
            "代码": member["代码"], "thscode": member["thscode"], "名称": member["名称"],
            "涨跌幅": ((float(close) - float(prior_close)) / float(prior_close)) * 100,
            "最新价": close, "今开": by_day[target].get("open_price"), "source_date": target,
        }, receipt

    records, receipts = [], []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(one, member): member["thscode"] for member in members}
        for future in as_completed(futures):
            record, receipt = future.result()
            records.append(record)
            receipts.append(receipt)
    frame = pd.DataFrame(records).sort_values("代码", kind="stable").reset_index(drop=True)
    frame.attrs.update({
        "source_date": target, "as_of": datetime.now(SHANGHAI).isoformat(),
        "date_verified": True, "closing_verified": True, "complete": len(records) == len(members),
        "source_contract": "FUYAO_HISTORICAL_DAILY_COHORT_V1",
        "validation_method": "code=0 + exact thscode + previous/target daily bars",
        "validation_evidence": {"requests": receipts, "row_count": len(records)},
    })
    return frame


def historical_883900(target: str, previous: str, *, session=None, timeout=20) -> dict:
    target, previous = _day(target), _day(previous)
    data, receipt = get_json(
        "/api/a-share-index/prices/historical",
        {"thscode": "883900.TI", "interval": "1d", "start": day_ms(previous), "end": day_ms(target)},
        session=session,
        timeout=timeout,
    )
    if data.get("thscode") != "883900.TI" or data.get("interval") != "1d":
        raise FuyaoError("883900 response identity or interval mismatch")
    rows = data.get("item")
    if not isinstance(rows, list):
        raise FuyaoError("883900 history is missing item rows")
    by_day = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("date_ms"), int):
            raise FuyaoError("883900 row is missing date_ms")
        observed = datetime.fromtimestamp(row["date_ms"] / 1000, SHANGHAI).strftime("%Y%m%d")
        by_day[observed] = row
    if target not in by_day or previous not in by_day:
        raise FuyaoError("883900 history does not cover requested trading days")
    close, prior_close = by_day[target].get("close_price"), by_day[previous].get("close_price")
    if isinstance(close, bool) or isinstance(prior_close, bool) or not isinstance(close, (int, float)) or not isinstance(prior_close, (int, float)) or prior_close == 0:
        raise FuyaoError("883900 close price is invalid")
    receipt.update({"requested_date": target, "previous_date": previous, "row_count": len(rows)})
    return {
        "code": "883900", "source": "FUYAO_883900_HISTORICAL", "status": "VALID",
        "value": ((float(close) - float(prior_close)) / float(prior_close)) * 100, "unit": "%",
        "identity_verified": True, "date_verified": True, "source_date": target,
        "source_field": "close_price/previous_close_price", "as_of": datetime.now(SHANGHAI).isoformat(),
        "validation_evidence": receipt,
    }


def historical_883900_range(start: str, end: str, *, session=None, timeout=20) -> tuple[dict, dict, str]:
    """Return one authenticated 883900 daily-history response with raw evidence.

    The caller supplies a verified trading calendar and is responsible for
    checking its required window.  Keeping that check outside this transport
    adapter prevents a missing session from being silently treated as a zero.
    """
    start, end = _day(start), _day(end)
    if start > end:
        raise ValueError("start must not be after end")
    import requests

    client = session or requests.Session()
    path = "/api/a-share-index/prices/historical"
    params = {"thscode": "883900.TI", "interval": "1d", "start": day_ms(start), "end": day_ms(end)}
    response = client.get(BASE_URL + path, params=params, headers={"X-api-key": api_key()}, timeout=timeout)
    receipt = _summary(path, params, response)
    raw_text = response.content.decode("utf-8", errors="replace")
    try:
        payload = response.json()
    except ValueError as exc:
        raise FuyaoError(f"non-JSON response ({response.status_code})") from exc
    if response.status_code != 200:
        raise FuyaoError(f"HTTP {response.status_code}")
    if not isinstance(payload, dict) or payload.get("code") != 0:
        code = payload.get("code") if isinstance(payload, dict) else None
        message = payload.get("message") if isinstance(payload, dict) else None
        raise FuyaoError(f"Fuyao business error: code={code}, message={message}")
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("thscode") != "883900.TI" or data.get("interval") != "1d":
        raise FuyaoError("883900 response identity or interval mismatch")
    rows = data.get("item")
    if not isinstance(rows, list) or not rows:
        raise FuyaoError("883900 history is missing item rows")
    observed = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("date_ms"), int):
            raise FuyaoError("883900 row is missing date_ms")
        trade_date = datetime.fromtimestamp(row["date_ms"] / 1000, SHANGHAI).strftime("%Y%m%d")
        if trade_date in observed:
            raise FuyaoError("883900 history has duplicate trading days")
        close = row.get("close_price")
        if isinstance(close, bool) or not isinstance(close, (int, float)) or close <= 0:
            raise FuyaoError("883900 history has an invalid close price")
        observed.add(trade_date)
    receipt.update({"request_id": payload.get("request_id"), "requested_start": start,
                    "requested_end": end, "row_count": len(rows)})
    return data, receipt, raw_text
