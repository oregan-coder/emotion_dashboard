# -*- coding: utf-8 -*-

"""
============================================================
        A股打板情绪仪表盘 V3.0.1

        数据获取模块（最终版）

功能：

1. 获取行情数据
2. 获取涨停池
3. 获取炸板池
4. 获取跌停池
5. 获取昨日涨停池
6. 支持历史日期补齐
7. 股票池统一过滤

股票范围：

保留：

000xxx
001xxx
002xxx
003xxx
300xxx
600xxx
601xxx
603xxx
605xxx
688xxx


剔除：

北交所
ST
*ST


============================================================
"""


from __future__ import annotations


from dataclasses import dataclass


from datetime import (
    datetime,
    timedelta
)


import os
import json


import re


from typing import Any


import pandas as pd


import akshare as ak


from input_contracts import (
    find_column,
    normalize_code
)


class DataCollectionError(RuntimeError):
    """A required collection branch failed; stop the current job explicitly."""

    def __init__(self, branch: str, cause: BaseException):
        self.branch = branch
        self.cause = cause
        super().__init__(f'{branch}采集失败: {cause}')


class DataCollectionCancelled(RuntimeError):
    """Cooperative cancellation between collection branches."""



# ============================================================
# 数据结构
# ============================================================


@dataclass
class DashboardData:

    date: str

    previous_date: str

    market: pd.DataFrame

    limit_up: pd.DataFrame

    previous_limit_up: pd.DataFrame

    limit_down: pd.DataFrame

    open_board: pd.DataFrame

    previous_pool_performance: pd.DataFrame



# ============================================================
# 日期处理
# ============================================================


def _date_text(
    value: str | datetime
) -> str:

    """
    日期统一格式

    YYYYMMDD
    """

    if isinstance(
        value,
        datetime
    ):

        return value.strftime(
            "%Y%m%d"
        )


    text = re.sub(
        r"\D",
        "",
        str(value)
    )


    if len(text) != 8:

        raise ValueError(
            "日期格式错误，应为YYYYMMDD"
        )


    return text



# ============================================================
# 安全DataFrame获取
# ============================================================


def _safe_frame(
    fetcher,
    *args: Any,
    **kwargs: Any
) -> pd.DataFrame:


    """
    数据接口异常保护

    单接口失败不影响整体运行
    """

    try:

        from source_transport import fetch_with_transport
        data = fetch_with_transport(fetcher, *args, **kwargs)


        if isinstance(
            data,
            pd.DataFrame
        ):

            return data


        return pd.DataFrame()


    except Exception as exc:
        result = pd.DataFrame()
        evidence = getattr(exc, "source_transport_evidence", None)
        result.attrs["fetch_error"] = {"status":"ERROR", "type":type(exc).__name__}
        if evidence is not None:
            result.attrs["source_transport"] = evidence
        return result


# ============================================================
# 问财备用
# ============================================================


def _wencai_frame(
    query: str
) -> pd.DataFrame:


    """
    同花顺问财备用接口

    需要：

    WENCAI_COOKIE

    """

    try:

        import pywencai


    except ImportError:

        return pd.DataFrame()



    cookie = os.environ.get(
        "WENCAI_COOKIE"
    )


    if not cookie:

        return pd.DataFrame()



    try:

        result = pywencai.get(
            query=query,
            loop=True,
            cookie=cookie
        )


        if isinstance(
            result,
            pd.DataFrame
        ):

            return result


        return pd.DataFrame()


    except Exception:

        return pd.DataFrame()



# ============================================================
# 交易日处理
# ============================================================


def get_trade_dates(
    end_date: str,
    count: int = 2
) -> list[str]:


    """
    获取最近交易日

    支持历史补齐

    例如：

    get_trade_dates(
        20260904,
        5
    )

    返回：

    20260831
    20260901
    20260902
    20260903
    20260904

    """


    end = datetime.strptime(
        _date_text(end_date),
        "%Y%m%d"
    )


    try:

        calendar = ak.tool_trade_date_hist_sina()


        date_col = next(
            (
                c
                for c in calendar.columns
                if str(c)
                in
                {
                    "trade_date",
                    "日期"
                }
            ),
            calendar.columns[0]
        )


        dates = pd.to_datetime(
            calendar[date_col],
            errors="coerce"
        ).dropna()



        valid = sorted(
            {
                item.strftime("%Y%m%d")
                for item in dates
                if item <= end
            }
        )


        if len(valid) >= count and len(dates) and dates.max().date() >= end.date():
            return valid[-count:]


    except Exception:

        pass



    raise RuntimeError("交易日历缺失或覆盖不足；禁止用工作日代替交易日。请检查实际日历源与缓存。")


def latest_trade_date() -> str:


    from datetime import timezone
    today = datetime.now(timezone(timedelta(hours=8))).strftime(
        "%Y%m%d"
    )


    return get_trade_dates(
        today,
        1
    )[0]
# ============================================================
# 股票池过滤
# ============================================================


def filter_stock_pool(
    df: pd.DataFrame
) -> pd.DataFrame:


    """
    统一股票范围过滤


    保留：

    000
    001
    002
    003
    300
    301
    600
    601
    603
    605
    688


    剔除：

    北交所

    ST

    *ST

    """


    if df is None:
        return pd.DataFrame()
    if df.empty:
        return df.copy()  # Keep transport/error evidence; empty is not verified zero.



    code_col = find_column(
        df,
        [
            "代码",
            "股票代码",
            "证券代码",
            "code",
            "symbol"
        ]
    )


    name_col = find_column(
        df,
        [
            "名称",
            "股票名称",
            "证券简称",
            "name"
        ]
    )



    if not code_col:

        return df.copy()



    result = df.copy()



    result["_code"] = (
        result[code_col]
        .map(normalize_code)
    )



    # 股票范围

    mask = result["_code"].str.startswith(
        (
            "000",
            "001",
            "002",
            "003",
            "300",
            "301",
            "600",
            "601",
            "603",
            "605",
            "688"
        )
    )



    # The legacy prefix list misses exchange-confirmed ChiNext code changes
    # (e.g. 300114 -> 302132). Retain unclassified 30-series records for the
    # existing exchange master + approved scope check; do NOT admit them by prefix.
    legacy_prefix_mask = mask.copy()
    mask |= result["_code"].str.match(r"^30[0-9]{4}$", na=False)
    unclassified = set(result.loc[mask & ~legacy_prefix_mask, "_code"])

    # 剔除ST

    if name_col:

        mask &= ~result[name_col].astype(str).str.contains(
            "ST",
            case=False,
            na=False
        )



    removed_codes = sorted(set(result.loc[~mask, "_code"]))
    result = result.loc[mask].copy()
    result.attrs["prefilter_evidence"] = {
        "stage": "EARLY_SCREEN_NOT_FINAL_APPROVED_SCOPE",
        "input_rows": len(df), "retained_rows": len(result),
        "removed_codes": removed_codes,
        "retained_board_unclassified": sorted(unclassified & set(result["_code"])),
        "note": "Retained unclassified records require exchange master identity; date and completeness remain unverified."
    }



    # 删除辅助字段

    result.drop(
        columns=[
            "_code"
        ],
        inplace=True,
        errors="ignore"
    )


    return result



# ============================================================
# 数据去重
# ============================================================


def _drop_duplicate_stock(
    df: pd.DataFrame
) -> pd.DataFrame:


    """
    同一股票只保留一条

    修复：

    涨停38只显示39只

    """

    if df.empty:

        return df



    code_col = find_column(
        df,
        [
            "代码",
            "股票代码",
            "证券代码",
            "code"
        ]
    )


    if not code_col:

        return df



    temp = df.copy()



    temp["_code"] = (
        temp[code_col]
        .map(normalize_code)
    )



    temp = temp.drop_duplicates(
        subset=[
            "_code"
        ],
        keep="first"
    )



    temp.drop(
        columns=[
            "_code"
        ],
        inplace=True,
        errors="ignore"
    )



    return temp



# ============================================================
# 涨停池
# ============================================================


def _limit_up_pool(
    date: str
) -> pd.DataFrame:


    """
    获取涨停池
    """


    ths = pd.DataFrame()  # token/cookie source not used by repaired production path



    df = (
        ths
        if not ths.empty
        else
        _safe_frame(
            ak.stock_zt_pool_em,
            date=date
        )
    )



    df = filter_stock_pool(
        df
    )


    df = _drop_duplicate_stock(
        df
    )


    return df



# ============================================================
# 跌停池
# ============================================================


def _limit_down_pool(
    date: str
) -> pd.DataFrame:


    """
    获取跌停池
    """


    ths = pd.DataFrame()



    df = (
        ths
        if not ths.empty
        else
        _safe_frame(
            ak.stock_zt_pool_dtgc_em,
            date=date
        )
    )



    df = filter_stock_pool(
        df
    )


    df = _drop_duplicate_stock(
        df
    )


    return df



# ============================================================
# 炸板池
# ============================================================


def _open_board_pool(
    date: str
) -> pd.DataFrame:


    """
    获取炸板池
    """


    ths = pd.DataFrame()



    df = (
        ths
        if not ths.empty
        else
        _safe_frame(
            ak.stock_zt_pool_zbgc_em,
            date=date
        )
    )



    df = filter_stock_pool(
        df
    )


    df = _drop_duplicate_stock(
        df
    )


    return df
# ============================================================
# 实时行情
# ============================================================


def _main_market() -> pd.DataFrame:
    """Retired entry: no full-market quote download or fallback after approval."""
    raise RuntimeError("FULL_MARKET_SPOT_DISABLED_USE_LEGULEGU_NATIVE_BREADTH")


# ============================================================
# 昨日涨停池
# ============================================================


def _previous_limit_pool(
    date: str
) -> pd.DataFrame:


    """
    获取昨日涨停表现池

    用于：

    高位反馈

    """



    df = _safe_frame(
        ak.stock_zt_pool_previous_em,
        date=date
    )


    if df.empty:

        return df



    df = filter_stock_pool(
        df
    )


    df = _drop_duplicate_stock(
        df
    )


    return df



# ============================================================
# BK1050 昨日涨停表现（含一字）
# ============================================================



def fetch_bk1050_yesterday_performance(
    date: str
) -> dict:
    """
    获取BK1050（昨日涨停表现，含一字）的历史日线数据

    来源: AKShare stock_board_concept_hist_em
    指标: 涨跌幅（百分数，如2.82表示2.82%）

    返回:
    {
        "value": 2.82,           # 涨跌幅（百分数）
        "status": "VALID",        # VALID / MISSING / ERROR
        "source": "BK1050",
        "source_field": "涨跌幅",
        "trade_date": "20260908",
        "retrieved_at": "2026-09-08T22:00:00+08:00",
        "error": None
    }
    """
    from datetime import datetime

    result = {
        "value": None,
        "status": "MISSING",
        "source": "BK1050",
        "source_field": "涨跌幅",
        "trade_date": date,
        "retrieved_at": datetime.now().isoformat() + "+08:00",
        "error": None,
    }

    try:
        import akshare as ak

        # 获取BK1050历史日线
        df = ak.stock_board_concept_hist_em(
            symbol="BK1050",
            period="daily",
            start_date=date,
            end_date=date,
            adjust=""
        )

        if df is not None and not df.empty:
            # 查找涨跌幅列
            pct_col = None
            for col in ["涨跌幅", "涨跌幅(%)", "pct_chg", "change_pct"]:
                if col in df.columns:
                    pct_col = col
                    break

            if pct_col and len(df) > 0:
                raw_val = df.iloc[0][pct_col]
                try:
                    val = float(raw_val)
                    import math
                    if math.isfinite(val):
                        result["value"] = val
                        result["status"] = "VALID"
                    else:
                        result["status"] = "ERROR"
                        result["error"] = f"非有限数值: {raw_val}"
                except (ValueError, TypeError):
                    result["status"] = "ERROR"
                    result["error"] = f"无法解析涨跌幅: {raw_val}"
            else:
                result["status"] = "ERROR"
                result["error"] = f"未找到涨跌幅列，可用列: {list(df.columns)}"
        else:
            result["status"] = "MISSING"
            result["error"] = f"BK1050在{date}无数据"

    except Exception as e:
        result["status"] = "ERROR"
        result["error"] = str(e)

    return result



# ============================================================
# 数据完整性检查
# ============================================================


def _empty_check(
    df: pd.DataFrame
) -> pd.DataFrame:


    """
    保证返回DataFrame

    """

    if isinstance(
        df,
        pd.DataFrame
    ):

        return df


    return pd.DataFrame()



# ============================================================
# 主数据入口
# ============================================================


def fetch_dashboard_data(
    date: str | None = None,
    *,
    progress_callback=None,
    cancel_event=None,
) -> DashboardData:


    """
    获取仪表盘全部数据


    支持：

    1. 今日运行

    2. 历史补齐运行


    例如：

    fetch_dashboard_data(
        "20260901"
    )


    会自动寻找：

    previous_date:

    20260831


    """


    target = _date_text(
        date
        if date
        else
        latest_trade_date()
    )



    trade_dates = get_trade_dates(
        target,
        2
    )



    previous_date = trade_dates[0]

    target = trade_dates[1]



    def _check_cancel():
        if cancel_event is not None and cancel_event.is_set():
            raise DataCollectionCancelled('采集任务已取消')

    def _collect(step_id, label, fetch):
        _check_cancel()
        if progress_callback:
            progress_callback(step_id, label, 'RUNNING')
        try:
            value = fetch()
            if isinstance(value, pd.DataFrame):
                fetch_error = value.attrs.get('fetch_error')
                if fetch_error:
                    raise RuntimeError(json.dumps(fetch_error, ensure_ascii=False))
            if isinstance(value, dict) and str(value.get('status', '')).upper() in {
                'ERROR', 'WORKER_ERROR', 'REQUEST_TIMEOUT', 'SUBPROCESS_ERROR', 'FAILED'
            }:
                raise RuntimeError(str(value.get('error') or value.get('status')))
            if progress_callback:
                progress_callback(step_id, label, 'DONE', {'rows': len(value) if hasattr(value, '__len__') else None})
            return value
        except DataCollectionCancelled:
            raise
        except Exception as exc:
            if progress_callback:
                progress_callback(step_id, label, 'FAILED', {'error': str(exc)})
            raise DataCollectionError(label, exc) from exc

    # Core prices first. Breadth is a separate item/value aggregate, never
    # masquerading as 5,000 stock records. A provider failure stops this job
    # and is surfaced to the caller instead of becoming an endless pending run.
    from market_breadth_legu import fetch_native, MODE
    data = DashboardData(
        date=target, previous_date=previous_date,
        market=pd.DataFrame(columns=["代码", "名称", "涨跌幅", "最新价", "今开"]),
        limit_up=_empty_check(_collect('limit_up', '采集涨停池', lambda: _limit_up_pool(target))),
        previous_limit_up=_empty_check(_collect('previous_limit_up', '采集昨日涨停池', lambda: _limit_up_pool(previous_date))),
        limit_down=_empty_check(_collect('limit_down', '采集跌停池', lambda: _limit_down_pool(target))),
        open_board=_empty_check(_collect('open_board', '采集炸板池', lambda: _open_board_pool(target))),
        previous_pool_performance=_empty_check(_collect('previous_pool_performance', '采集昨日涨停表现', lambda: _previous_limit_pool(target))),
    )
    data.collection_mode = MODE
    data.input_kind = "LIVE_POOL_SCOPE_WITH_LEGU_NATIVE"
    data.market.attrs.update(status="NOT_REQUESTED_BY_APPROVED_POLICY",
        full_market_spot_requested=False, full_market_price_universe=False)
    data.market_breadth_raw = _collect('market_breadth', '采集市场宽度', lambda: fetch_native(target))
    _check_cancel()
    return data
