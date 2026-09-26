# -*- coding: utf-8 -*-

"""
============================================================
A股二进三决策模型 V2.1（结构修正版）

V2.1变更要点（严格按照《V2.1结构修正规格》）：
1. 删除重复计分：2→3成功率仅在市场环境使用；高度稀缺性仅在龙头资格使用
2. 删除龙头资格-E板块内部排名（与A/C重复）
3. 重构预期差：仅保留明日空间+一致预期风险，删除历史同类/2→3反馈/同板块竞争
4. 新增梯队健康度：首板/二板比值 + 二板/三板比值
5. 重构筹码结构：换手率仅出现一次（在二板质量中），新增筹码交换充分性+获利盘压力
6. 新增市场环境评级上限机制
7. 风险扣分上限20分，同类风险不重复处罚
8. 评分精度仅保留整数和0.5分
9. 评分解释树：每个评分可反向追踪到原始数据
10. 预留竞价反馈数据库字段
11. 未来函数检查：仅使用T日收盘前已确定数据

核心原则：严禁未来函数。仅使用截至当日收盘已确定的数据。
============================================================
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from core.input_contracts import find_column, normalize_code, number, integer, price, board_count

# V2.2 周期状态识别器
try:
    from analytics.cycle_state_detector import detect_cycle_state
    V22_AVAILABLE = True
except ImportError:
    V22_AVAILABLE = False


# ============================================================
# 评级标准
# ============================================================

GRADE_TABLE = [
    (90, "S", "核心候选"),
    (82, "A", "强候选"),
    (74, "B", "观察候选"),
    (65, "C", "低优先级"),
    (0,  "D", "放弃"),
]

GRADE_ORDER = {"S": 5, "A": 4, "B": 3, "C": 2, "D": 1}


# ============================================================
# 工具函数
# ============================================================

def _safe_num(stock: dict, key: str, default=None):
    """
    P03A R3: 安全获取数值，缺失返回None，不补0
    处理None、NaN、inf、空字符串、bool
    """
    val = stock.get(key)
    if val is None:
        return default
    # bool（包括numpy bool）不能按1/0进入数值
    if isinstance(val, (bool, np.bool_)):
        return default
    if isinstance(val, str) and val.strip() == "":
        return default
    try:
        result = float(val)
        if np.isnan(result) or np.isinf(result):
            return default
        return result
    except (ValueError, TypeError, OverflowError):
        return default


def _safe_int(stock: dict, key: str, default=None):
    """安全获取整数，缺失返回None"""
    val = _safe_num(stock, key, default)
    if val is None:
        return default
    try:
        return integer(val)
    except (ValueError, TypeError, OverflowError):
        return default


def _safe_sum(*args):
    """P03A R3.1: 完整求和，有None时返回None（不视作完整分）
    用于模块total/完整研究分。依赖未知时不能跳过None视作完整。
    """
    if any(a is None for a in args):
        return None
    return sum(args)


def _known_subtotal(*args):
    """P03A R3.1: 已知小计，跳过None求和
    仅用于显示已知分项的小计，明确非完整分，不得用于排名/评级/交易。
    """
    valid = [a for a in args if a is not None]
    if not valid:
        return None
    return sum(valid)


def _fmt_amount(val) -> str:
    """P03A R3: 格式化金额，None显示待证据"""
    if val is None:
        return "待证据"
    try:
        val = float(val)
    except (ValueError, TypeError):
        return "待证据"
    if val >= 1e8:
        return f"{val / 1e8:.2f}亿"
    if val >= 1e4:
        return f"{val / 1e4:.0f}万"
    return f"{val:.0f}"


def _fmt_time(t: str) -> str:
    if not t or len(t) != 6:
        return "--:--"
    return f"{t[:2]}:{t[2:4]}"


def _market_type(code: str, market_board=None) -> tuple[str, float | None]:
    """Board category, not authoritative daily limit price; master wins."""
    labels={'SSE_MAIN_A':('主板',10.0),'SZSE_MAIN_A':('主板',10.0),
            'CHINEXT_A':('创业板',20.0),'STAR_A':('科创板',20.0)}
    if isinstance(market_board,str) and market_board in labels:
        return labels[market_board]
    if isinstance(market_board,str) and market_board == 'CONFLICT':
        return '板块待证据',None
    if code.startswith(('300','301')): return '创业板',20.0
    if code.startswith(('688','689')): return '科创板',20.0
    if code.startswith('30'): return '板块待证据',None
    return '主板',10.0


def _grade(score: float) -> tuple[str, str]:
    for threshold, g, desc in GRADE_TABLE:
        if score >= threshold:
            return g, desc
    return "D", "放弃"


def _round_half(val: float) -> float:
    """V2.1精度控制：仅保留整数和0.5分
    P03A R3.1: None返回None，不报错
    """
    if val is None:
        return None
    return round(val * 2) / 2


def _cap_grade(grade: str, max_grade: str) -> str:
    """评级上限：如果当前评级高于上限，返回上限评级"""
    if GRADE_ORDER.get(grade, 0) > GRADE_ORDER.get(max_grade, 0):
        return max_grade
    return grade


def _detect_core_2board_v22(market_data: dict):
    """
    V2.2：检测是否存在核心二板
    定义：二板数量≤3 且 存在题材排名前3 且 封板资金排名前20%的二板股
    P03A R3.1 V2: 有任何seal_amount未知时返回None（未知），不偷偷缩小母体。
    返回：True/False/None（None表示证据不足，无法确定）
    """
    second_boards = market_data.get("second_board_stocks", [])
    if not second_boards or len(second_boards) > 3:
        return False

    concept_stats = market_data.get("concept_stats", {})

    # 收集所有二板的封板资金
    # P03A R3.1 V2: 检查全部候选的seal_amount是否都已知，有未知则完整母体结论未知
    all_seal_amounts = []
    for s in second_boards:
        amt = _safe_num(s, "seal_amount")
        if amt is None:
            # 有未知成员，完整母体排名无法确定，不缩小母体，返回None
            return None
        all_seal_amounts.append(amt)
    if not all_seal_amounts:
        return None

    # 前20%的阈值（全部已知时才计算）
    top20_idx = max(0, int(len(all_seal_amounts) * 0.2) - 1)
    top20_threshold = sorted(all_seal_amounts, reverse=True)[top20_idx]

    for stock in second_boards:
        # 题材排名前3
        top_concept = stock.get("top_concept", "")
        concept_rank = concept_stats.get(top_concept, {}).get("rank", 999)
        if concept_rank > 3:
            continue

        # 封板资金前20%
        stock_seal = _safe_num(stock, "seal_amount")
        if stock_seal is not None and stock_seal >= top20_threshold:
            return True

    return False


def _calc_seal_time_rank_pct(stock: dict, all_stocks: list) -> float:
    """计算封板时间排名百分比（越小越好，0=最快）"""
    if not all_stocks:
        return 50.0
    seal_times = sorted([s.get("seal_time", "999999") for s in all_stocks])
    stock_time = stock.get("seal_time", "999999")
    try:
        rank = seal_times.index(stock_time) + 1
        return round(rank / len(seal_times) * 100, 1)
    except (ValueError, ZeroDivisionError):
        return 50.0


def _calc_seal_amount_rank_pct(stock: dict, all_stocks: list) -> float:
    """计算封板资金排名百分比（越小越好，0=最大）
    P03A R3.1 V2: 修复None排序崩溃，同时不偷偷缩小排名母体。
    有任何候选的seal_amount未知时，完整母体排名无法确定，返回None。
    只有全部候选的seal_amount都已知时，才计算完整母体排名。
    """
    if not all_stocks:
        return None
    # 检查全部候选的seal_amount是否都已知
    all_amounts = []
    for s in all_stocks:
        amt = _safe_num(s, "seal_amount")
        if amt is None:
            # 有未知成员，完整母体排名无法确定，不缩小母体
            return None
        all_amounts.append(amt)
    stock_amount = _safe_num(stock, "seal_amount")
    if stock_amount is None:
        return None
    # 全部已知时才计算完整母体排名
    sorted_amounts = sorted(all_amounts, reverse=True)
    try:
        rank = sorted_amounts.index(stock_amount) + 1
        return round(rank / len(sorted_amounts) * 100, 1)
    except (ValueError, ZeroDivisionError):
        return None


def _is_not_late_seal(seal_time: str) -> bool:
    """判断是否非尾盘板（14:00以前封板）"""
    if not seal_time or len(seal_time) < 4:
        return False
    try:
        hour = int(seal_time[:2])
        minute = int(seal_time[2:4])
        return hour < 14 or (hour == 14 and minute == 0)
    except (ValueError, IndexError):
        return False


def parse_limit_up_reason(value) -> list[str]:
    """Turn the provider's ``A+B+C`` limit-up reason into ordered themes.

    The reason is evidence from the canonical Fuyao limit-up pool.  We keep its
    terms verbatim apart from whitespace and separators; it is not replaced by
    a secondary provider's concept taxonomy.
    """
    if isinstance(value, (list, tuple)):
        values = value
    elif value is None or (isinstance(value, float) and np.isnan(value)):
        values = []
    else:
        values = re.split(r"[+＋,，、;；|/\\\n]+", str(value))
    concepts = []
    for item in values:
        name = str(item).strip()
        if name and name not in concepts:
            concepts.append(name)
    return concepts


# ============================================================
# 数据提取：从原始涨停池 DataFrame 提取完整字段
# ============================================================

def _extract_stocks(limit_up_df) -> list[dict]:
    """提取每只涨停股的完整字段"""
    if limit_up_df is None or not hasattr(limit_up_df, "empty") or limit_up_df.empty:
        return []

    code_col = find_column(limit_up_df, ["代码", "股票代码", "证券代码", "code"])
    name_col = find_column(limit_up_df, ["名称", "股票名称", "证券简称", "name"])
    board_col = find_column(limit_up_df, ["连板数", "连续涨停天数", "涨停统计", "板数", "board"])
    time_col = find_column(limit_up_df, ["首次封板时间", "首封时间", "封板时间"])
    last_time_col = find_column(limit_up_df, ["最后封板时间", "最后封板", "末次封板时间"])
    amount_col = find_column(limit_up_df, ["封板资金", "封单资金"])
    turnover_col = find_column(limit_up_df, ["换手率", "换手"])
    open_count_col = find_column(limit_up_df, ["炸板次数", "炸板数"])
    volume_col = find_column(limit_up_df, ["成交额", "成交金额"])
    industry_col = find_column(limit_up_df, ["所属行业", "行业"])
    reason_col = find_column(limit_up_df, ["涨停原因", "涨停原因分类", "limit_up_reason"])
    change_col = find_column(limit_up_df, ["涨跌幅", "涨幅"])
    float_mv_col = find_column(limit_up_df, ["流通市值", "流通市值(元)"])
    close_col = find_column(limit_up_df, ["最新价", "收盘价", "close", "最新"])

    if not code_col or not board_col:
        return []

    rows = []
    for _, row in limit_up_df.iterrows():
        code = normalize_code(row.get(code_col))
        if not code:
            continue

        board = board_count(row.get(board_col))
        if board is None:
            continue

        name = str(row.get(name_col, code)).strip() if name_col else code

        def _seal_time(value, default=""):
            """Normalize common provider forms (HH:MM, HHMM, HH:MM:SS)."""
            digits = re.sub(r"\D", "", str(value or "").strip())
            if len(digits) == 4:
                digits += "00"
            if len(digits) != 6:
                return default
            try:
                hour, minute, second = int(digits[:2]), int(digits[2:4]), int(digits[4:])
            except ValueError:
                return default
            return digits if hour < 24 and minute < 60 and second < 60 else default

        seal_time = _seal_time(row.get(time_col), "235959") if time_col else "235959"

        last_seal_time = ""
        if last_time_col:
            last_seal_time = _seal_time(row.get(last_time_col))

        # P03A R2: 区分真正缺失和有效0，不把缺失伪装成有效0
        def _safe_float_or_none(val):
            """安全转换为float，缺失返回None，有效0保留0
            P03A R3.1: 拒绝Python/numpy bool，不变成1.0
            """
            if val is None:
                return None
            # P03A R3.1: 拒绝bool（包括numpy bool），不变成1.0
            if isinstance(val, (bool, np.bool_)):
                return None
            if isinstance(val, float) and (np.isnan(val) or np.isinf(val)):
                return None
            try:
                if isinstance(val, str) and val.strip() == "":
                    return None
                result = float(val)
                if np.isnan(result) or np.isinf(result):
                    return None
                return result
            except (ValueError, TypeError, OverflowError):
                return None

        def _safe_int_or_none(val):
            """安全转换为int，缺失返回None，有效0保留0
            P03A R3.1: 拒绝Python/numpy bool，不变成1；捕获OverflowError（如'inf'）
            """
            if val is None:
                return None
            # P03A R3.1: 拒绝bool（包括numpy bool），不变成1
            if isinstance(val, (bool, np.bool_)):
                return None
            if isinstance(val, float) and (np.isnan(val) or np.isinf(val)):
                return None
            try:
                if isinstance(val, str) and val.strip() == "":
                    return None
                return integer(val)
            except (ValueError, TypeError, OverflowError):
                return None

        seal_amount = _safe_float_or_none(row.get(amount_col)) if amount_col else None
        turnover = _safe_float_or_none(row.get(turnover_col)) if turnover_col else None
        open_count = _safe_int_or_none(row.get(open_count_col)) if open_count_col else None
        volume = _safe_float_or_none(row.get(volume_col)) if volume_col else None

        industry = str(row.get(industry_col, "")).strip() if industry_col else ""
        limit_up_reason = row.get(reason_col) if reason_col else None
        reason_concepts = parse_limit_up_reason(limit_up_reason)

        float_mv = 0.0
        if float_mv_col:
            try:
                float_mv = float(row.get(float_mv_col, 0) or 0)
            except Exception:
                float_mv = 0.0

        # P02B: 收盘价（从涨停池"最新价"字段提取，收盘后获取即为当日收盘价）
        # 必须是大于0的有限数，bool、NaN、inf、负数不可当作有效价格
        close = None
        close_status = "MISSING"
        if close_col:
            try:
                raw_close = row.get(close_col)
                if raw_close is not None and str(raw_close).strip() != "":
                    # 排除bool类型
                    if isinstance(raw_close, (bool, np.bool_)):
                        close_status = "INVALID_BOOL"
                    else:
                        close_val = float(raw_close)
                        import math
                        if math.isfinite(close_val) and close_val > 0:
                            close = close_val
                            close_status = "VALID"
                        elif not math.isfinite(close_val):
                            close_status = "INVALID_NON_FINITE"
                        elif close_val <= 0:
                            close_status = "INVALID_NON_POSITIVE"
            except (ValueError, TypeError):
                close_status = "INVALID_PARSE_ERROR"
            except Exception:
                close_status = "ERROR"

        mtype, limit_pct = _market_type(code, row.get("market_board"))

        rows.append({
            "code": code,
            "name": name,
            "board": board,
            "seal_time": seal_time,
            "last_seal_time": last_seal_time,
            "seal_amount": seal_amount,
            "turnover": turnover,
            "open_count": open_count,
            "volume": volume,
            "float_mv": float_mv,
            "industry": industry,
            "limit_up_reason": limit_up_reason,
            "reason_concepts": reason_concepts,
            "concept_source": "THS_LIMIT_UP_REASON" if reason_concepts else None,
            "market_type": mtype,
            "limit_pct": limit_pct,
            "close": close,
            "close_status": close_status,
            "close_source_field": close_col,
            "close_source_date": row.get("source_date", limit_up_df.attrs.get("source_date")),
            "close_snapshot_time": row.get("as_of", limit_up_df.attrs.get("as_of")),  # P03A R3.1 V5: 使用实际命中的列名
        })

    return rows


# ============================================================
# ① 市场接力环境：25分（V2.1不变，2→3成功率唯一使用处）
# ============================================================

def _score_market_env(stocks: list[dict], open_board_count: int,
                      rate_23: float, highest_board: int) -> dict:
    """Legacy thresholds retained. Every branch returns a structured module."""
    count = len(stocks)
    attempted_open = integer(open_board_count, minimum=0)
    rate = number(rate_23, minimum=0, maximum=100)
    height = integer(highest_board, minimum=0)
    s_a = next((v for threshold, v in [(80,5),(60,4),(40,3),(25,2),(15,1)] if count >= threshold), 0)
    br = attempted_open / (count + attempted_open) * 100 if attempted_open is not None and count + attempted_open > 0 else None
    s_b = None if br is None else next((v for threshold,v in [(10,5),(15,4),(20,3),(30,1)] if br < threshold), 0)
    s_c = None if rate is None else next((v for threshold,v in [(60,7),(45,6),(35,4),(25,2),(15,1)] if rate >= threshold), 0)
    s_e = None if height is None else (3 if height >= 6 else 2 if height == 5 else 1 if height == 4 else 0)
    details = {
        "涨停家数": {"score":s_a,"max":5,"value":f"{count}只","raw":count},
        "炸板率": {"score":s_b,"max":5,"value":f"{br:.1f}%" if br is not None else "待证据","raw":br},
        "2→3成功率": {"score":s_c,"max":7,"value":f"{rate:.1f}%" if rate is not None else "待证据","raw":rate},
        "连板赚钱效应": {"score":3,"max":5,"value":"数据不足（连板股涨跌幅未接入），旧函数固定3分，仅供未验证旧规则对照","raw":None,"legacy_fixed_missing_bonus":True},
        "市场最高高度": {"score":s_e,"max":3,"value":f"{height}板" if height is not None else "待证据","raw":height},
    }
    total = _round_half(_safe_sum(*(d["score"] for d in details.values())))
    return {"total":total,"max":25,"details":details,"status":"RESEARCH_ONLY" if total is not None else "DATA_PENDING"}



def _score_market_env_from_context(stocks: list[dict], open_board_count: int,
                      rate_23: float, highest_board: int, *, approved_market_evidence=None) -> dict:
    """Legacy thresholds retained; approved context never re-derives unknowns from filtered frames."""
    count = len(stocks)
    attempted_open = integer(open_board_count, minimum=0)
    rate = number(rate_23, minimum=0, maximum=100)
    height = integer(highest_board, minimum=0)
    br = attempted_open / (count + attempted_open) * 100 if attempted_open is not None and count + attempted_open > 0 else None
    if approved_market_evidence is not None:
        evidence = approved_market_evidence if isinstance(approved_market_evidence, dict) else {}
        counts = evidence.get("counts") or {}
        failed = evidence.get("failed_limitup_rate") or {}
        count = integer(counts.get("up"), minimum=0) if counts.get("status") == "VALID" else None
        br = number(failed.get("value"), minimum=0, maximum=100) if failed.get("status") == "VALID" else None
    s_a = None if count is None else next((v for threshold, v in [(80,5),(60,4),(40,3),(25,2),(15,1)] if count >= threshold), 0)
    s_b = None if br is None else next((v for threshold,v in [(10,5),(15,4),(20,3),(30,1)] if br < threshold), 0)
    s_c = None if rate is None else next((v for threshold,v in [(60,7),(45,6),(35,4),(25,2),(15,1)] if rate >= threshold), 0)
    s_e = None if height is None else (3 if height >= 6 else 2 if height == 5 else 1 if height == 4 else 0)
    details = {
        "涨停家数": {"score":s_a,"max":5,"value":f"{count}只" if count is not None else "待证据","raw":count},
        "炸板率": {"score":s_b,"max":5,"value":f"{br:.1f}%" if br is not None else "待证据","raw":br},
        "2→3成功率": {"score":s_c,"max":7,"value":f"{rate:.1f}%" if rate is not None else "待证据","raw":rate},
        "连板赚钱效应": {"score":3,"max":5,"value":"数据不足（连板股涨跌幅未接入），旧函数固定3分，仅供未验证旧规则对照","raw":None,"legacy_fixed_missing_bonus":True},
        "市场最高高度": {"score":s_e,"max":3,"value":f"{height}板" if height is not None else "待证据","raw":height},
    }
    if approved_market_evidence is not None:
        for name, pointer in (("涨停家数", "input_evidence.counts.up"), ("炸板率", "input_evidence.failed_limitup_rate.value")):
            details[name]["source_path"] = pointer
            details[name]["input_status"] = "VALID" if details[name]["raw"] is not None else "DATA_PENDING"
            details[name]["scope"] = "APPROVED_MARKET_CONTEXT_NOT_CANDIDATE_SUBSET"
    total = _round_half(_safe_sum(*(d["score"] for d in details.values())))
    return {"total":total,"max":25,"details":details,"status":"RESEARCH_ONLY" if total is not None else "DATA_PENDING"}



# ============================================================
# ② 主线/题材强度：15分（V2.1不变）
# ============================================================

def _score_theme(stock: dict, concept_stats: dict, all_stocks: list[dict]) -> dict:
    """
    主线/题材强度 15分
    A: 板块涨停数量排名 4分
    B: 题材持续性 4分（需要历史数据，不足给保守分）
    C: 板块成交额/参与度 3分
    D: 题材催化强度 4分（需要人工标签，默认一般逻辑）
    """
    concepts = stock.get("concepts", [])
    if not concepts:
        return {
            "total": 4, "max": 15,
            "details": {
                "板块涨停排名": {"score": 0, "max": 4, "value": "无概念数据", "raw": None},
                "题材持续性": {"score": 2, "max": 4, "value": "数据不足，保守2分", "raw": None},
                "板块参与度": {"score": 1, "max": 3, "value": "无概念数据", "raw": None},
                "题材催化强度": {"score": 1, "max": 4, "value": "默认弱逻辑", "raw": None},
            }
        }

    # 找最强概念
    best_concept = None
    best_rank = 999
    best_count = 0
    for c in concepts:
        info = concept_stats.get(c, {})
        rank = info.get("rank", 999)
        count = info.get("count", 0)
        if rank < best_rank or (rank == best_rank and count > best_count):
            best_rank = rank
            best_count = count
            best_concept = c

    # A: 板块涨停数量排名
    if best_rank == 1:
        s_a = 4
    elif best_rank == 2:
        s_a = 3
    elif best_rank == 3:
        s_a = 2
    elif best_rank <= 5:
        s_a = 1
    else:
        s_a = 0

    # B: 题材持续性（需要最近3-5日板块涨停变化，数据不足给保守分）
    if best_count >= 5:
        s_b = 3
        b_note = f"今日{best_count}只涨停，偏强势持续"
    elif best_count >= 3:
        s_b = 2
        b_note = f"今日{best_count}只涨停，震荡"
    else:
        s_b = 1
        b_note = f"今日{best_count}只涨停，偏弱（历史数据不足）"

    # C: 板块成交额/参与度
    first_count = concept_stats.get(best_concept, {}).get("first_count", 0)
    participation = best_count + first_count * 0.5
    if participation >= 8:
        s_c = 3
        c_note = "市场第一梯队"
    elif participation >= 5:
        s_c = 2
        c_note = "第二梯队"
    elif participation >= 3:
        s_c = 1
        c_note = "普通"
    else:
        s_c = 0
        c_note = "明显弱势"

    # D: 题材催化强度（需要人工标签/数据库，默认"一般逻辑"2分）
    s_d = 2
    d_note = "默认一般逻辑（未接入催化标签库）"

    total = _round_half(_safe_sum(s_a, s_b, s_c, s_d))

    return {
        "total": total, "max": 15,
        "top_concept": best_concept,
        "details": {
            "板块涨停排名": {"score": s_a, "max": 4, "value": f"第{best_rank}名（{best_count}只）", "raw": best_rank},
            "题材持续性": {"score": s_b, "max": 4, "value": b_note, "raw": best_count},
            "板块参与度": {"score": s_c, "max": 3, "value": c_note, "raw": participation},
            "题材催化强度": {"score": s_d, "max": 4, "value": d_note, "raw": None},
        }
    }


# ============================================================
# ③ 个股龙头资格：17分（V2.1：删除E板块内部排名，从20→17）
# ============================================================

def _score_leader(stock: dict, concept_stats: dict, all_second: list[dict]) -> dict:
    """
    个股龙头资格 17分（V2.1：删除E板块内部排名，消除与A/C的重复计分）
    A: 板块地位 6分
    B: 高度稀缺性 4分（V2.1：全模型唯一使用同概念二板数量的地方）
    C: 市场辨识度 4分
    D: 启动先后 3分
    删除E: 板块内部综合排名（与A/C重复计分）
    """
    concepts = stock.get("concepts", [])
    code = stock["code"]

    # 找最强概念
    best_concept = None
    best_count = 0
    for c in concepts:
        count = concept_stats.get(c, {}).get("count", 0)
        if count > best_count:
            best_count = count
            best_concept = c

    # 同概念二板列表
    same_concept_seconds = []
    if best_concept:
        for s in all_second:
            if best_concept in s.get("concepts", []):
                same_concept_seconds.append(s)

    # A: 板块地位（根据封板时间、封板资金、在同概念二板中的排名）
    if not same_concept_seconds:
        s_a = 4
        a_note = "同概念无二板对比，默认核心前排"
    else:
        sorted_by_time = sorted(same_concept_seconds, key=lambda x: x["seal_time"])
        rank_in_concept = next((i for i, s in enumerate(sorted_by_time) if s["code"] == code), -1)

        if rank_in_concept == 0 and _safe_num(stock, "seal_amount", 0) >= 1e8:
            s_a = 6
            a_note = "绝对核心（最早封板+封板资金过亿）"
        elif rank_in_concept == 0:
            s_a = 5
            a_note = "高度核心（同概念最早封板）"
        elif rank_in_concept == 1:
            s_a = 4
            a_note = "核心前排"
        elif rank_in_concept == 2:
            s_a = 2
            a_note = "前排跟随"
        else:
            s_a = 1
            a_note = "普通跟风"

    # B: 高度稀缺性（V2.1：全模型唯一使用同概念二板数量的地方）
    n_same = len(same_concept_seconds)
    if n_same <= 1:
        s_b = 4
        b_note = "唯一核心二板"
    elif n_same == 2:
        s_b = 3
        b_note = "少数核心之一"
    elif n_same <= 4:
        s_b = 2
        b_note = f"二板较多（{n_same}只）"
    else:
        s_b = 1
        b_note = f"高度同质化（{n_same}只）"

    # C: 市场辨识度（根据成交额、封板资金）
    # P03A R3: 安全获取，缺失标记待证据
    volume = _safe_num(stock, "volume")
    seal_amount = _safe_num(stock, "seal_amount")
    if volume is None or seal_amount is None:
        s_c = None
        c_note = f"成交额{_fmt_amount(volume)}，封单{_fmt_amount(seal_amount)}，待证据"
    else:
        vol_score = min(volume / 5e8, 1) * 2
        amount_score = min(seal_amount / 2e8, 1) * 2
        s_c = _round_half(min(vol_score + amount_score, 4))
        c_note = f"成交额{_fmt_amount(volume)}，封单{_fmt_amount(seal_amount)}"

    # D: 启动先后（首封时间）
    st = stock.get("seal_time", "235959") or "235959"
    if st <= "100000":
        s_d = 3
        d_note = f"10:00前封板（{_fmt_time(st)}）"
    elif st <= "110000":
        s_d = 2
        d_note = f"11:00前封板（{_fmt_time(st)}）"
    elif st <= "140000":
        s_d = 1
        d_note = f"14:00前封板（{_fmt_time(st)}）"
    else:
        s_d = 0
        d_note = f"尾盘封板（{_fmt_time(st)}）"

    # P03A R3: 安全求和，跳过None
    total = _round_half(_safe_sum(s_a, s_b, s_c, s_d))

    return {
        "total": total, "max": 17,
        "details": {
            "板块地位": {"score": s_a, "max": 6, "value": a_note, "raw": rank_in_concept if same_concept_seconds else None},
            "高度稀缺性": {"score": s_b, "max": 4, "value": b_note, "raw": n_same},
            "市场辨识度": {"score": s_c, "max": 4, "value": c_note, "raw": _safe_num(stock, "volume")},
            "启动先后": {"score": s_d, "max": 3, "value": d_note, "raw": st},
        }
    }


# ============================================================
# ④ 明日预期差：7分（V2.1：大幅重构，删除3个重复指标）
# ============================================================

def _score_expectation(stock: dict, highest_board: int) -> dict:
    """
    明日预期差 7分（V2.1重构版）

    V2.1变更：
    - 删除A历史同类表现（用2→3成功率代理，与市场环境重复）
    - 删除B 2→3成功反馈（与市场环境重复）
    - 删除D同板块竞争（与龙头资格-高度稀缺性重复）
    - 保留A明日空间 4分（客观指标：最高板-候选板的高度差）
    - 保留B一致预期风险 3分（半客观：封板时间+封单+换手组合判断）

    预期差定义：市场当前认知与个股真实强度之间的偏离。
    当前仅实现可客观量化的两个维度，其余维度待历史数据积累后补充。
    """
    # A: 明日空间（当前最高板 vs 候选3板的高度差）
    space = highest_board - 3 if highest_board is not None else None
    if space is None:
        s_a, a_note = None, "待证据（完整市场最高板未知）"
    elif space >= 3:
        s_a = 4
        a_note = f"空间明显（当前{highest_board}板，候选3板，差{space}板）"
    elif space >= 2:
        s_a = 3
        a_note = f"空间正常（当前{highest_board}板，候选3板）"
    elif space >= 1:
        s_a = 2
        a_note = f"空间一般（当前{highest_board}板，候选3板）"
    elif space == 0:
        s_a = 1
        a_note = f"空间有限（当前最高{highest_board}板，候选即最高）"
    else:
        s_a = 0
        a_note = "高度压制"

    # B: 一致预期风险（封板太早+封单太大+换手低 = 过度一致，预期差小）
    # P03A R3.1: 缺失时返回None，不流入有利分支。未知不是已证明充分换手。
    st = stock.get("seal_time", "235959") or "235959"
    seal_amount = _safe_num(stock, "seal_amount")
    turnover = _safe_num(stock, "turnover")
    if seal_amount is None or turnover is None:
        # 关键输入缺失，待证据，不默认有利分支
        s_b = None
        missing_fields = []
        if seal_amount is None:
            missing_fields.append("封板资金")
        if turnover is None:
            missing_fields.append("换手率")
        b_note = f"待证据（{'、'.join(missing_fields)}缺失，无法判断一致预期风险）"
    elif st <= "094500" and seal_amount >= 2e8 and turnover < 8:
        s_b = 1
        b_note = "预期偏高（一字/秒板，过度一致）"
    elif st <= "100000" and seal_amount >= 1e8:
        s_b = 2
        b_note = "正常预期（强势封板但仍有换手）"
    else:
        s_b = 3
        b_note = "有预期差空间（非一字，有充分换手）"

    total = _round_half(_safe_sum(s_a, s_b))

    return {
        "total": total, "max": 7,
        "details": {
            "明日空间": {"score": s_a, "max": 4, "value": a_note, "raw": space},
            "一致预期风险": {"score": s_b, "max": 3, "value": b_note, "raw": st},
        }
    }


# ============================================================
# ⑤ 板块梯队：15分（V2.1：新增梯队健康度7分，从8→15）
# ============================================================

def _score_ladder(stock: dict, concept_stats: dict, all_stocks: list[dict]) -> dict:
    """
    板块梯队 15分（V2.1：新增D梯队健康度7分）
    A: 梯队完整度 4分
    B: 首板助攻 2分
    C: 同题材晋级质量 2分
    D: 梯队健康度 7分（V2.1新增：首板/二板比值3.5分 + 二板/三板比值3.5分）
       目的：区分"首板大量堆积"和"真正形成晋级链条"
    """
    concepts = stock.get("concepts", [])
    best_concept = None
    best_count = 0
    for c in concepts:
        count = concept_stats.get(c, {}).get("count", 0)
        if count > best_count:
            best_count = count
            best_concept = c

    info = concept_stats.get(best_concept, {}) if best_concept else {}
    first_count = info.get("first_count", 0)
    second_count = info.get("second_count", 0)
    third_plus = info.get("third_plus", 0)

    # A: 梯队完整度
    levels = 0
    if first_count > 0:
        levels += 1
    if second_count > 0:
        levels += 1
    if third_plus > 0:
        levels += 1

    if levels >= 3 and third_plus >= 1:
        s_a = 4
        a_note = f"完整梯队（首板{first_count}/二板{second_count}/高标{third_plus}）"
    elif levels >= 2:
        s_a = 3
        a_note = f"较完整（首板{first_count}/二板{second_count}/高标{third_plus}）"
    elif levels == 1 and first_count >= 3:
        s_a = 2
        a_note = f"普通（仅首板{first_count}只助攻）"
    elif levels == 1:
        s_a = 1
        a_note = "单点结构"
    else:
        s_a = 0
        a_note = "孤军作战"

    # B: 首板助攻
    if first_count >= 5:
        s_b = 2
        b_note = f"首板助攻强劲（{first_count}只）"
    elif first_count >= 2:
        s_b = 1
        b_note = f"首板助攻一般（{first_count}只）"
    else:
        s_b = 0
        b_note = f"首板助攻不足（{first_count}只）"

    # C: 同题材晋级质量
    if third_plus >= 1 and second_count >= 2 and first_count >= 3:
        s_c = 2
        c_note = "梯队晋级质量高（高标+多二板+首板增加）"
    elif second_count >= 2 and first_count >= 2:
        s_c = 1
        c_note = "梯队晋级质量一般"
    else:
        s_c = 0
        c_note = "梯队晋级质量弱"

    # D: 梯队健康度（V2.1新增）
    # D1: 首板/二板比值（理想2-5，说明有足够首板助攻但不过度堆积）
    if second_count > 0:
        ratio12 = first_count / second_count
    else:
        ratio12 = 999  # 无二板，比值无穷大

    if 2 <= ratio12 <= 5:
        s_d1 = 3.5
        d1_note = f"首板/二板={ratio12:.1f}（健康）"
    elif (1 <= ratio12 < 2) or (5 < ratio12 <= 8):
        s_d1 = 2
        d1_note = f"首板/二板={ratio12:.1f}（一般）"
    else:
        s_d1 = 0.5
        d1_note = f"首板/二板={ratio12:.1f}（{'首板堆积' if ratio12 > 8 else '首板不足'}）"

    # D2: 二板/三板比值（理想1-3，说明二板能有效晋级到三板）
    if third_plus > 0:
        ratio23 = second_count / third_plus
    else:
        ratio23 = 999  # 无三板，比值无穷大

    if 1 <= ratio23 <= 3:
        s_d2 = 3.5
        d2_note = f"二板/三板={ratio23:.1f}（晋级链条健康）"
    elif (0.5 <= ratio23 < 1) or (3 < ratio23 <= 6):
        s_d2 = 2
        d2_note = f"二板/三板={ratio23:.1f}（晋级一般）"
    else:
        s_d2 = 0.5
        d2_note = f"二板/三板={ratio23:.1f}（{'晋级断层' if ratio23 > 6 else '高标过多'}）"

    s_d = _round_half(_safe_sum(s_d1, s_d2))
    d_note = f"{d1_note}；{d2_note}"

    total = _round_half(_safe_sum(s_a, s_b, s_c, s_d))

    return {
        "total": total, "max": 15,
        "details": {
            "梯队完整度": {"score": s_a, "max": 4, "value": a_note, "raw": levels},
            "首板助攻": {"score": s_b, "max": 2, "value": b_note, "raw": first_count},
            "同题材晋级质量": {"score": s_c, "max": 2, "value": c_note, "raw": second_count},
            "梯队健康度": {"score": s_d, "max": 7, "value": d_note, "raw": {"ratio12": ratio12, "ratio23": ratio23}},
        }
    }


# ============================================================
# ⑥ 二板质量与筹码：21分（V2.1：并入筹码结构，新增E/F）
# ============================================================

def _score_quality_chips(stock: dict) -> dict:
    """
    二板质量与筹码 21分（V2.1：原二板质量7分 + 重构后的筹码结构14分）

    V2.1变更：
    - 换手率仅出现一次（在D成交量合理性中），消除原筹码模块的重复计分
    - 新增E筹码交换充分性 4分（成交额/流通市值比2分 + 放量倍数2分）
    - 新增F获利盘压力 5分（连续涨停兑现压力2分 + 距前期高点3分，数据不足保守分）
    - 删除原筹码模块的A二板换手率（与D重复）、B连续两日成交结构（用换手率代理重复）、C获利盘压力（用换手率代理重复）

    A: 封板时间 2分
    B: 炸板次数 2分
    C: 封板后稳定性 1分
    D: 成交量合理性 2分（换手率唯一使用处）
    E: 筹码交换充分性 4分（V2.1新增）
    F: 获利盘压力 6分（V2.1新增，重新定义后不再使用换手率）
    """
    # A: 封板时间
    st = stock["seal_time"]
    if st <= "100000":
        s_a = 2.0
        a_note = f"10:00前封板（{_fmt_time(st)}）"
    elif st <= "110000":
        s_a = 1.5
        a_note = f"10:00-11:00封板（{_fmt_time(st)}）"
    elif st <= "140000":
        s_a = 1.0
        a_note = f"11:00-14:00封板（{_fmt_time(st)}）"
    else:
        s_a = 0.5
        a_note = f"14:00后封板（{_fmt_time(st)}）"

    # B: 炸板次数
    # P03A R3: 安全获取，缺失标记待证据，不补0
    oc = _safe_int(stock, "open_count")
    if oc is None:
        s_b = None
        b_note = "炸板次数缺失，待证据"
    elif oc == 0:
        s_b = 2
        b_note = "0次炸板"
    elif oc == 1:
        s_b = 1
        b_note = "1次炸板"
    elif oc == 2:
        s_b = 0.5
        b_note = "2次炸板"
    else:
        s_b = 0
        b_note = f"{oc}次炸板"

    # C: 封板后稳定性（根据最后封板时间和炸板次数）
    if oc is not None and oc == 0 and stock.get("last_seal_time") and stock["last_seal_time"] <= "103000":
        s_c = 1
        c_note = "封板后稳定（早封板+0炸板）"
    elif oc is not None and oc <= 1:
        s_c = 0.5
        c_note = "封板后中等稳定"
    elif oc is None:
        s_c = None
        c_note = "炸板次数缺失，待证据"
    else:
        s_c = 0
        c_note = "封板后不稳定（多次炸板）"

    # D: 成交量合理性（V2.1：换手率全模型唯一使用处）
    # P03A R3: 安全获取，缺失标记待证据
    turnover = _safe_num(stock, "turnover")
    if turnover is None:
        s_d = None
        d_note = "换手率缺失，待证据"
    elif 5 <= turnover <= 20:
        s_d = 2
        d_note = f"合理放量（换手{turnover:.1f}%）"
    elif 3 <= turnover < 5 or 20 < turnover <= 30:
        s_d = 1.5
        d_note = f"正常（换手{turnover:.1f}%）"
    elif turnover < 3 or turnover > 30:
        s_d = 1
        d_note = f"明显异常（换手{turnover:.1f}%）"
    else:
        s_d = 0
        d_note = "极端爆量"

    # E: 筹码交换充分性（V2.1新增）
    # E1: 成交额/流通市值比（理想3%-10%，说明筹码充分交换）
    float_mv = _safe_num(stock, "float_mv", 0)
    volume = _safe_num(stock, "volume")
    if float_mv and float_mv > 0 and volume is not None:
        vol_ratio = volume / float_mv * 100
        if 3 <= vol_ratio <= 10:
            s_e1 = 2
            e1_note = f"成交额/流通市值={vol_ratio:.1f}%（充分交换）"
        elif (1 <= vol_ratio < 3) or (10 < vol_ratio <= 20):
            s_e1 = 1
            e1_note = f"成交额/流通市值={vol_ratio:.1f}%（一般）"
        else:
            s_e1 = 0.5
            e1_note = f"成交额/流通市值={vol_ratio:.1f}%（{'交换不足' if vol_ratio < 1 else '过度交换'}）"
    elif volume is None:
        s_e1 = None
        e1_note = "成交额缺失，待证据"
        vol_ratio = None
    else:
        s_e1 = 1
        e1_note = "流通市值数据缺失，保守1分"
        vol_ratio = None

    # E2: 放量倍数（今日成交额/昨日成交额，数据不足用换手率代理，保守1分）
    # 理想1.5-3倍：健康放量；<1倍：缩量一致；>5倍：爆量分歧
    s_e2 = 1
    e2_note = "昨日成交额未接入，保守1分（待历史数据库）"

    # P03A R3: 安全求和，跳过None
    s_e = _round_half(_safe_sum(s_e1, s_e2))
    e_note = f"{e1_note}；{e2_note}"

    # F: 获利盘压力（V2.1新增，重新定义后不再使用换手率）
    # F1: 连续涨停后的兑现压力（2板本身有一定获利盘，固定评估）
    # 逻辑：连板天数越多，获利盘越厚，兑现压力越大
    board = stock["board"]
    if board <= 2:
        s_f1 = 2
        f1_note = f"{board}板，获利盘压力可控"
    elif board == 3:
        s_f1 = 1.5
        f1_note = f"{board}板，获利盘有一定压力"
    else:
        s_f1 = 1
        f1_note = f"{board}板，获利盘压力较大"

    # F2: 距前期高点距离（数据不足，保守2分；待接入历史K线数据）
    # 逻辑：距前期高点越近，套牢盘压力越大；越远，上方空间越大
    s_f2 = 2
    f2_note = "前期高点数据未接入，保守2分（待历史K线数据库）"

    s_f = _round_half(_safe_sum(s_f1, s_f2))
    f_note = f"{f1_note}；{f2_note}"

    total = _round_half(_safe_sum(s_a, s_b, s_c, s_d, s_e, s_f))

    return {
        "total": total, "max": 21,
        "details": {
            "封板时间": {"score": s_a, "max": 2, "value": a_note, "raw": st},
            "炸板次数": {"score": s_b, "max": 2, "value": b_note, "raw": oc},
            "封板后稳定性": {"score": s_c, "max": 1, "value": c_note, "raw": oc},
            "成交量合理性": {"score": s_d, "max": 2, "value": d_note, "raw": turnover},
            "筹码交换充分性": {"score": s_e, "max": 4, "value": e_note, "raw": vol_ratio},
            "获利盘压力": {"score": s_f, "max": 6, "value": f_note, "raw": board},
        }
    }


# ============================================================
# 风险扣分（V2.1：上限20分，同类风险不重复处罚）
# ============================================================

def _risk_deduction(stock: dict, market: dict) -> tuple[float, list]:
    """
    风险扣分 V2.1：
    - 上限20分
    - 同类风险不重复处罚（市场级风险已在市场环境评分中体现的，不再大额扣分）
    - 个股级风险正常扣分

    返回 (总扣分, 风险列表)
    """
    risks = []
    total_deduct = 0

    # === 个股级风险（正常扣分）===

    # P03A R3: 安全获取数值，缺失不触发风险
    oc = _safe_int(stock, "open_count")
    seal_time = stock.get("seal_time", "")
    seal_amount = _safe_num(stock, "seal_amount")
    turnover = _safe_num(stock, "turnover")

    # 1. 炸板次数多
    if oc is not None and oc >= 3:
        risks.append(("严重", f"二板当日炸板{oc}次，封板意愿弱"))
        total_deduct += 12
    elif oc is not None and oc == 2:
        risks.append(("较大", "二板当日炸板2次，筹码不稳定"))
        total_deduct += 8

    # 2. 尾盘封板
    if seal_time and seal_time >= "143000":
        risks.append(("中等", f"尾盘封板（{_fmt_time(seal_time)}），非主动攻击"))
        total_deduct += 5

    # 3. 封板资金不足
    if seal_amount is not None and 0 < seal_amount < 3e7:
        risks.append(("轻微", f"封板资金仅{_fmt_amount(seal_amount)}，封单偏弱"))
        total_deduct += 3

    # 4. 换手率极端（个股级，与市场环境无关）
    if turnover is not None and turnover > 35:
        risks.append(("中等", f"换手率{turnover:.1f}%过高，分歧巨大"))
        total_deduct += 5

    # === 市场级风险（V2.1：已在市场环境评分中体现的，减半扣分，避免重复处罚）===

    # 5. 市场炸板率高（V2.1：如果市场环境-炸板率已得0分，减半扣分）
    break_rate_detail = market["details"].get("炸板率", {})
    if break_rate_detail.get("score") is not None and break_rate_detail["score"] <= 1:
        # 已在市场环境中得0分（扣5分），风险扣分减半
        risks.append(("较大", f"市场炸板率{break_rate_detail.get('value', '')}，接力环境差（已在市场环境评分中体现，减半扣分）"))
        total_deduct += 4  # 原8分，减半为4分

    # 6. 2→3成功率极低（V2.1：如果市场环境-2→3成功率已得0分，减半扣分）
    rate_detail = market["details"].get("2→3成功率", {})
    if rate_detail.get("score", 7) == 0:
        # 已在市场环境中得0分（扣7分），风险扣分减半
        risks.append(("严重", f"今日2→3成功率{rate_detail.get('value', '')}，三板几乎无赚钱效应（已在市场环境评分中体现，减半扣分）"))
        total_deduct += 6  # 原12分，减半为6分

    # V2.1：风险扣分上限20分
    final_deduct = min(total_deduct, 20)
    if total_deduct > 20:
        risks.append(("说明", f"风险扣分合计{total_deduct}分，按上限20分计"))

    return final_deduct, risks


# ============================================================
# 一票否决（V2.1不变）
# ============================================================

def _veto_check(stock: dict, market: dict, theme: dict) -> tuple[bool, str]:
    """
    一票否决：市场级 / 题材级 / 个股级 / 数据级
    返回 (是否否决, 原因)
    """
    # 市场级：2→3成功率=0 且 炸板率>=30%
    rate_score = market["details"].get("2→3成功率", {}).get("score", 7)
    break_score = market["details"].get("炸板率", {}).get("score", 5)
    if rate_score == 0 and break_score == 0:
        return True, "市场级否决：2→3成功率为0且炸板率≥30%，禁止主动出手"

    # 题材级：题材涨停数<2 且 无首板助攻
    theme_total = theme.get("total", 0)
    if theme_total is not None and theme_total < 5:
        return True, f"题材级否决：题材强度仅{theme_total}/15，题材明显退潮"

    # 个股级：炸板>=3次 且 尾盘封板
    # P03A R3: 安全获取，缺失不触发否决
    oc = _safe_int(stock, "open_count")
    seal_time = stock.get("seal_time", "")
    if oc is not None and oc >= 3 and seal_time and seal_time >= "140000":
        return True, "个股级否决：多次炸板且尾盘封板，明显后排补涨末端"

    # 数据级：关键数据缺失
    if not stock.get("concepts"):
        return True, "数据级否决：无概念数据，无法评估题材环境"

    return False, ""


# ============================================================
# 市场环境评级上限（V2.1新增）
# ============================================================

def _market_cap_grade(grade: str, market_score: float) -> tuple[str, str]:
    """
    V2.1新增：市场环境评级上限机制
    市场环境决定允许出手等级，而不是简单影响总分。

    市场环境(25分制)：
    - >=20: 最高允许S
    - 15-20: 最高允许A
    - 10-15: 最高允许B
    - <10: 最高允许C
    """
    if market_score >= 20:
        max_grade = "S"
        cap_note = ""
    elif market_score >= 15:
        max_grade = "A"
        cap_note = f"市场环境{market_score}/25，评级上限A"
    elif market_score >= 10:
        max_grade = "B"
        cap_note = f"市场环境{market_score}/25，评级上限B"
    else:
        max_grade = "C"
        cap_note = f"市场环境{market_score}/25，评级上限C"

    capped = _cap_grade(grade, max_grade)
    return capped, cap_note


# ============================================================
# 置信度（V2.1不变）
# ============================================================

def _calc_confidence(modules: dict) -> tuple[str, float]:
    """
    置信度：根据有效指标数量、数据完整率、各模块分数一致性
    高 ≥90% / 中 75-90% / 低 <75%
    """
    total_items = 0
    valid_items = 0
    for mod in modules.values():
        for detail in mod.get("details", {}).values():
            total_items += 1
            val = detail.get("value", "")
            if "数据不足" not in val and "未接入" not in val and "默认" not in val and "缺失" not in val:
                valid_items += 1

    completeness = valid_items / total_items if total_items > 0 else 0

    rates = []
    for mod in modules.values():
        # P03A R3.1: mod["total"]为None时跳过，不参与一致性计算
        if mod.get("max", 0) > 0 and mod.get("total") is not None:
            rates.append(mod["total"] / mod["max"])
    if rates:
        avg = sum(rates) / len(rates)
        variance = sum((r - avg) ** 2 for r in rates) / len(rates)
        consistency = 1 - min(variance ** 0.5, 0.5) * 2
    else:
        consistency = 0.5

    confidence_pct = completeness * 0.6 + consistency * 0.4

    if confidence_pct >= 0.9:
        return "高", confidence_pct
    elif confidence_pct >= 0.75:
        return "中", confidence_pct
    else:
        return "低", confidence_pct


# ============================================================
# 打板理由 / 放弃理由 生成（V2.1更新模块名和权重）
# ============================================================

def _gen_buy_reasons(stock: dict, modules: dict, top_concept: str, grade: str) -> list[str]:
    """
    V2.1：D级/C级股票不生成打板理由，仅生成"个股优势"
    B级及以上才生成打板理由
    P03A R3.1: grade为None时返回空列表（待证据）
    """
    if grade is None:
        return []
    candidates = []

    # D级/C级不生成打板理由
    if grade in ("D", "C"):
        # 仅列个股优势（非打板理由）
        l = modules["leader"]
        if l.get("total") is not None and l["total"] >= 12:
            candidates.append(f"个股优势：龙头资格较强（{l['total']}/17分），{l['details']['板块地位']['value']}")
        t = modules["theme"]
        if t.get("total") is not None and t["total"] >= 10:
            candidates.append(f"个股优势：所属「{top_concept}」题材不弱（{t['total']}/15分）")
        q = modules["quality_chips"]
        if q.get("total") is not None and q["total"] >= 14:
            candidates.append(f"个股优势：二板质量与筹码较好（{q['total']}/21分）")
        return candidates[:3]

    # B级及以上生成打板理由
    m = modules["market"]
    if m.get("total") is not None and m["total"] >= 18:
        candidates.append(f"市场接力环境良好（{m['total']}/25分），2→3成功率{m['details']['2→3成功率']['value']}")
    elif m.get("total") is not None and m["total"] >= 14:
        candidates.append(f"市场接力环境尚可（{m['total']}/25分）")

    t = modules["theme"]
    if t.get("total") is not None and t["total"] >= 11:
        candidates.append(f"所属「{top_concept}」题材强度高（{t['total']}/15分），{t['details']['板块涨停排名']['value']}")

    l = modules["leader"]
    if l.get("total") is not None and l["total"] >= 12:
        candidates.append(f"个股龙头资格强（{l['total']}/17分），{l['details']['板块地位']['value']}")
    if l["details"]["高度稀缺性"].get("score") is not None and l["details"]["高度稀缺性"]["score"] >= 3:
        candidates.append(f"高度稀缺性好：{l['details']['高度稀缺性']['value']}")

    e = modules["expectation"]
    if e["details"]["明日空间"].get("score") is not None and e["details"]["明日空间"]["score"] >= 3:
        candidates.append(f"明日空间大：{e['details']['明日空间']['value']}")

    la = modules["ladder"]
    if la.get("total") is not None and la["total"] >= 10:
        candidates.append(f"板块梯队健康（{la['total']}/15分），{la['details']['梯队健康度']['value']}")

    q = modules["quality_chips"]
    if q.get("total") is not None and q["total"] >= 15:
        candidates.append(f"二板质量与筹码好（{q['total']}/21分），{q['details']['封板时间']['value']}，{q['details']['炸板次数']['value']}")

    return candidates[:5]


def _gen_skip_reasons(stock: dict, modules: dict, risks: list) -> list[str]:
    """生成放弃/风险理由"""
    candidates = []

    for level, desc in risks:
        candidates.append(f"[{level}] {desc}")

    m = modules["market"]
    if m.get("total") is not None and m["total"] < 12:
        candidates.append(f"市场接力环境偏弱（{m['total']}/25分），炸板率{m['details']['炸板率']['value']}")

    t = modules["theme"]
    if t.get("total") is not None and t["total"] < 8:
        candidates.append(f"题材强度不足（{t['total']}/15分），{t['details']['题材持续性']['value']}")

    l = modules["leader"]
    if l.get("total") is not None and l["total"] < 10:
        candidates.append(f"个股非板块核心（龙头资格{l['total']}/17分），{l['details']['板块地位']['value']}")

    e = modules["expectation"]
    if e["details"]["明日空间"].get("score") is not None and e["details"]["明日空间"]["score"] <= 1:
        candidates.append(f"明日空间有限：{e['details']['明日空间']['value']}")

    la = modules["ladder"]
    if la["details"]["梯队健康度"].get("score") is not None and la["details"]["梯队健康度"]["score"] <= 2:
        candidates.append(f"梯队健康度差：{la['details']['梯队健康度']['value']}")

    q = modules["quality_chips"]
    if q.get("total") is not None and q["total"] < 12:
        candidates.append(f"二板质量与筹码弱（{q['total']}/21分），{q['details']['封板时间']['value']}，{q['details']['炸板次数']['value']}")

    return candidates[:5]


def _gen_intraday_conditions(stock: dict, top_concept: str) -> list[str]:
    """生成明日盘中确认条件"""
    conditions = [
        "竞价不能出现明显负反馈（低开>3%或竞价量异常萎缩）",
        f"「{top_concept}」板块核心股不能出现大幅低开（>5%）",
        "个股必须保持板块前排（封板时间不晚于同板块其他二板）",
        "分时攻击过程中不能出现明显弱于同题材核心的表现",
        "真正触及三板时，若市场整体出现高标/板块集体转弱，则取消交易",
    ]

    if _safe_int(stock, "open_count", 0) >= 1:
        conditions.append("该股昨日有炸板记录，今日需观察是否快速弱转强")
    if stock["seal_time"] >= "140000":
        conditions.append("该股昨日尾盘封板，今日需确认是否有主动攻击性")

    return conditions


# ============================================================
# 概念统计
# ============================================================

def _build_concept_stats(stocks: list[dict]) -> dict:
    """构建概念统计：每个概念的涨停数、首板数、二板数、高标数、排名"""
    concept_map = {}
    for s in stocks:
        for c in s.get("concepts", []):
            if c not in concept_map:
                concept_map[c] = {"count": 0, "first_count": 0, "second_count": 0, "third_plus": 0, "stocks": []}
            concept_map[c]["count"] += 1
            concept_map[c]["stocks"].append(s["code"])
            if s["board"] == 1:
                concept_map[c]["first_count"] += 1
            elif s["board"] == 2:
                concept_map[c]["second_count"] += 1
            else:
                concept_map[c]["third_plus"] += 1

    sorted_concepts = sorted(concept_map.items(), key=lambda x: -x[1]["count"])
    for i, (name, info) in enumerate(sorted_concepts):
        info["rank"] = i + 1

    return concept_map


# ============================================================
# 主入口
# ============================================================

def evaluate_three_board(
    limit_up_df,
    previous_limit_up_df=None,
    open_board_df=None,
    date: str = "",
    rate_23: float = None,
    highest_board: int = None,
    high_board_fail_rate: float = None,
    prior_limitup_continue_rate: float = None,
    candidate_filter_evidence: dict = None,
    highest_board_evidence: dict = None,
    approved_market_evidence: dict = None,
) -> list[dict]:
    """
    二进三决策模型 V2.1 主入口（结构修正版）

    V2.1六大模块（100分）：
    ① 市场接力环境 25分
    ② 主线/题材强度 15分
    ③ 个股龙头资格 17分（删除E内部排名）
    ④ 明日预期差 7分（仅保留明日空间+一致预期风险）
    ⑤ 板块梯队 15分（新增梯队健康度7分）
    ⑥ 二板质量与筹码 21分（并入筹码结构，新增筹码交换充分性+获利盘压力）

    附加：风险扣分（上限20分）、一票否决、市场环境评级上限、置信度、评级

    核心原则：严禁未来函数。仅使用截至当日收盘已确定的数据。
    """
    # 提取股票数据
    stocks = _extract_stocks(limit_up_df)
    if not stocks:
        return []

    # 炸板数量
    open_board_count = len(open_board_df) if open_board_df is not None and hasattr(open_board_df, "empty") else None
    rate_23 = number(rate_23, minimum=0, maximum=100)
    highest_board = integer(highest_board, minimum=0)
    high_board_fail_rate = number(high_board_fail_rate, minimum=0, maximum=100)
    prior_limitup_continue_rate = number(prior_limitup_continue_rate, minimum=0, maximum=100)
    # 2B proof is validated upstream; no fallback to the candidate/subset maximum.
    if highest_board_evidence is not None and highest_board_evidence.get("status") != "VALID":
        highest_board = None

    # 同花顺涨停原因是题材的第一来源。只对原始原因缺失的股票回退到
    # F10，避免东方财富的分类体系覆盖同花顺的当日涨停归因。
    try:
        from scoring.pool_analyzer import fetch_concepts
        import requests
        session = requests.Session()
        for s in stocks:
            if s.get("reason_concepts"):
                s["concepts"] = list(s["reason_concepts"])
                s["concept_source"] = "THS_LIMIT_UP_REASON"
            else:
                s["concepts"] = fetch_concepts(s["code"], s["industry"], date, session)
                s["concept_source"] = "EASTMONEY_F10_FALLBACK"
    except Exception:
        for s in stocks:
            if s.get("reason_concepts"):
                s["concepts"] = list(s["reason_concepts"])
                s["concept_source"] = "THS_LIMIT_UP_REASON"
            else:
                s["concepts"] = [s["industry"]] if s["industry"] else []
                s["concept_source"] = "INDUSTRY_FALLBACK" if s["industry"] else "MISSING"

    # 构建概念统计
    concept_stats = _build_concept_stats(stocks)

    # 筛选二板股
    second_board = [s for s in stocks if s["board"] == 2]
    if not second_board:
        return []

    # V2.3：构建题材最高板映射表（用于B条件判定）
    # 遍历所有涨停股，记录每个概念对应的最高连板数
    # V2.3 Phase1 v3: 增加母体完整度检查，覆盖率不足时标记DATA_PENDING
    theme_highest_board_map = {}
    theme_stocks_map = {}  # {concept: [code, ...]}
    stocks_with_concepts = 0
    stocks_without_concepts = 0
    for s in stocks:
        board = int(s.get("board", 0) or 0)
        concepts = s.get("concepts", []) or []
        code = s.get("code", "")
        if concepts:
            stocks_with_concepts += 1
        else:
            stocks_without_concepts += 1
        for concept in concepts:
            if concept not in theme_highest_board_map or board > theme_highest_board_map[concept]:
                theme_highest_board_map[concept] = board
            if concept not in theme_stocks_map:
                theme_stocks_map[concept] = []
            theme_stocks_map[concept].append(code)

    # V2.3 Phase1 v3: 题材母体完整度信息
    theme_universe_info = {
        "total_limit_up_stocks": len(stocks),
        "stocks_with_concepts": stocks_with_concepts,
        "stocks_without_concepts": stocks_without_concepts,
        "concept_coverage_rate": (stocks_with_concepts / len(stocks) * 100) if stocks else 0,
        "universe_complete": stocks_without_concepts == 0,
        "concept_source": "THS_LIMIT_UP_REASON_PRIMARY; EASTMONEY_F10_FALLBACK_FOR_MISSING",
        "historical_validity_status": "UNVERIFIED_HISTORICAL",
        "note": "如果universe_complete=False，is_theme_highest_board的可信度下降；后续阶段应输出DATA_PENDING",
    }

    # 市场环境（所有二板共享）
    market_env = (_score_market_env(stocks, open_board_count, rate_23, highest_board)
                  if approved_market_evidence is None else
                  _score_market_env_from_context(stocks, open_board_count, rate_23, highest_board,
                                                 approved_market_evidence=approved_market_evidence))

    # ============================================================
    # V2.2 周期状态识别（市场级别）
    # ============================================================
    board_counts = {}
    for item in stocks:
        board_counts[item["board"]] = board_counts.get(item["board"], 0) + 1
    v22_market_data = {
        "highest_board":highest_board, "rate_23":rate_23,
        "board_4_count":board_counts.get(4,0), "board_3_count":board_counts.get(3,0),
        "board_3_plus_count":sum(v for k,v in board_counts.items() if k >= 3),
        "open_board_rate":market_env["details"]["炸板率"]["raw"],
        "second_board_stocks":second_board, "concept_stats":concept_stats,
        "high_board_fail_rate":high_board_fail_rate,
        "prior_limitup_continue_rate":prior_limitup_continue_rate,
    }
    v22_market_data["has_core_2board"] = _detect_core_2board_v22(v22_market_data)
    v22_market_state = None
    v22_error = None
    cycle_inputs_complete = all(v22_market_data.get(k) is not None for k in
        ("highest_board","rate_23","open_board_rate","high_board_fail_rate","prior_limitup_continue_rate","has_core_2board"))
    if V22_AVAILABLE and cycle_inputs_complete and market_env["total"] is not None:
        try:
            v22_market_state = detect_cycle_state(market_data=v22_market_data, stock=None, rating="C", market_score=market_env["total"])
        except Exception as exc:
            v22_error = {"status":"ERROR","type":type(exc).__name__,"message":str(exc)}

    # One failing legacy submodule cannot erase an otherwise known candidate.
    def score_module(func, budget, *args):
        try:
            result = func(*args)
            if isinstance(result, dict) and "total" in result:
                return result
            raise TypeError("score module did not return a structured result")
        except Exception as exc:
            return {"total":None,"max":budget,"details":{},"status":"ERROR",
                    "error":{"type":type(exc).__name__,"message":str(exc),"function":func.__name__}}

    # 逐只评分
    results = []
    for stock in second_board:
        theme_rank = None
        is_theme_highest = None
        # ② 题材
        theme = score_module(_score_theme, 15, stock, concept_stats, stocks)
        top_concept = theme.get("top_concept", stock.get("concepts", [""])[0] if stock.get("concepts") else "")

        # ③ 龙头资格
        leader = score_module(_score_leader, 17, stock, concept_stats, second_board)

        # ④ 预期差（V2.1：不再传入rate_23和all_second，消除重复计分）
        expectation = score_module(_score_expectation, 7, stock, highest_board)

        # ⑤ 梯队（V2.1：含梯队健康度）
        ladder = score_module(_score_ladder, 15, stock, concept_stats, stocks)

        # ⑥ 二板质量与筹码（V2.1：合并模块）
        quality_chips = score_module(_score_quality_chips, 21, stock)

        modules = {
            "market": market_env,
            "theme": theme,
            "leader": leader,
            "expectation": expectation,
            "ladder": ladder,
            "quality_chips": quality_chips,
        }

        # 原始总分
        # P03A R3.1: 使用_safe_sum，有模块total为None时返回None（不视作完整分）
        raw_score = _round_half(_safe_sum(*[m["total"] for m in modules.values()]))
        # 已知小计（仅用于显示，不得用于排名/评级）
        known_subtotal = _round_half(_known_subtotal(*[m["total"] for m in modules.values()]))

        # 风险扣分（V2.1：上限20分，同类风险不重复处罚）
        risk_deduct, risks = _risk_deduction(stock, market_env)

        # 一票否决
        vetoed, veto_reason = _veto_check(stock, market_env, theme)

        # 最终评分
        # P03A R3.1: raw_score为None时，final_score也为None（待证据）
        if vetoed:
            final_score = 0
            grade, grade_desc = "D", "放弃（一票否决）"
            cap_note = ""
        elif raw_score is None:
            final_score = None
            grade, grade_desc = None, "待证据（关键评分输入缺失）"
            cap_note = ""
        else:
            final_score = _round_half(raw_score - risk_deduct)
            grade, grade_desc = _grade(final_score)
            # V2.1：市场环境评级上限
            grade, cap_note = _market_cap_grade(grade, market_env["total"])
            if cap_note:
                grade_desc = f"{grade_desc}（{cap_note}）"

        # 置信度
        confidence, confidence_pct = _calc_confidence(modules)

        # 打板理由（V2.1：D/C级不生成打板理由）
        buy_reasons = _gen_buy_reasons(stock, modules, top_concept, grade) if raw_score is not None else []

        # 放弃理由
        skip_reasons = _gen_skip_reasons(stock, modules, risks) if all(m.get("details") for m in modules.values()) else ["存在评分模块错误，保留候选与已知字段"]

        # 明日盘中确认条件
        intraday = _gen_intraday_conditions(stock, top_concept)

        # V2.1：竞价反馈数据库预留字段（次日数据回填用，不参与评分）
        next_day_feedback = {
            "date": "",
            "open_pct": None,      # 次日开盘涨幅
            "high_pct": None,      # 次日最高涨幅
            "low_pct": None,       # 次日最低涨幅
            "close_pct": None,     # 次日收盘涨幅
            "auction_pct": None,   # 次日竞价涨幅
            "promoted": None,      # 是否晋级三板
            "open_board": None,    # 次日是否炸板
        }

        # ============================================================
        # V2.2 周期状态识别（个股级别）
        # ============================================================
        v22_stock_result = None
        if V22_AVAILABLE and v22_market_state is not None:
            # V2.3：从theme模块获取统一题材排名
            theme_rank = theme.get("details", {}).get("板块涨停排名", {}).get("raw")
            if theme_rank is None:
                theme_rank = concept_stats.get(top_concept, {}).get("rank", 999)

            # V2.3：真正计算题材最高板（B条件）
            # V2.3 Phase1 v3.1: 真正三值逻辑 TRUE/FALSE/UNKNOWN
            # - 母体不完整且结论不稳健 → is_theme_highest = None, theme_status = "DATA_PENDING"
            # - 母体完整或结论稳健 → 使用通用公式计算TRUE/FALSE
            # - VALID_ROBUST: 缺失股票的board_count低于已观测到的theme_max_board，最高板结论数学稳健
            is_theme_highest = None  # 默认UNKNOWN
            theme_highest_status = "DATA_PENDING"
            theme_highest_evidence = {
                "top_concept": top_concept,
                "stock_board_count": stock.get("board", 2),
                "theme_max_board": None,
                "theme_stock_count": 0,
                "universe_complete": theme_universe_info["universe_complete"],
                "concept_coverage_rate": theme_universe_info["concept_coverage_rate"],
                "historical_validity_status": "UNVERIFIED_HISTORICAL",
                "formula": "is_theme_highest = (stock_board_count == theme_max_board)",
                "three_value_logic": "TRUE / FALSE / UNKNOWN",
            }
            if top_concept and top_concept in theme_highest_board_map:
                highest_board_in_theme = theme_highest_board_map[top_concept]
                theme_highest_evidence["theme_max_board"] = highest_board_in_theme
                theme_highest_evidence["theme_stock_count"] = len(theme_stocks_map.get(top_concept, []))

                # 检查最高板结论是否稳健（VALID_ROBUST）
                # 逻辑：缺失概念数据的股票的board_count，如果都低于已观测到的theme_max_board，
                # 则即使它们也属于该题材，也不可能改变theme_max_board
                max_board_robust = False
                if not theme_universe_info["universe_complete"]:
                    # 获取缺失概念数据的股票的最高板数
                    missing_stocks_max_board = 0
                    for s in stocks:
                        if not s.get("concepts"):
                            missing_board = int(s.get("board", 0) or 0)
                            if missing_board > missing_stocks_max_board:
                                missing_stocks_max_board = missing_board
                    # 如果缺失股票的最高板数 < 已观测到的theme_max_board，则结论稳健
                    if missing_stocks_max_board < highest_board_in_theme:
                        max_board_robust = True
                        theme_highest_evidence["max_board_result_is_robust"] = True
                        theme_highest_evidence["missing_stocks_max_board"] = missing_stocks_max_board
                        theme_highest_evidence["robust_reason"] = f"缺失概念股票最高{missing_stocks_max_board}板 < 已观测{highest_board_in_theme}板，不可能改变最高板结论"
                    else:
                        theme_highest_evidence["max_board_result_is_robust"] = False
                        theme_highest_evidence["missing_stocks_max_board"] = missing_stocks_max_board

                # 判定三值逻辑
                if theme_universe_info["universe_complete"] or max_board_robust:
                    # 母体完整或最高板结论稳健 → 可以计算TRUE/FALSE
                    stock_board = int(stock.get("board", 2) or 2)
                    if stock_board == highest_board_in_theme:
                        is_theme_highest = True
                        theme_highest_status = "VALID"
                    else:
                        is_theme_highest = False
                        theme_highest_status = "VALID"
                    if max_board_robust and not theme_universe_info["universe_complete"]:
                        theme_highest_status = "VALID_ROBUST"
                        theme_highest_evidence["theme_count_status"] = "PARTIAL"
                        theme_highest_evidence["note"] = "最高板结论稳健(VALID_ROBUST)，但题材成员统计不完整(PARTIAL)"
                else:
                    # 母体不完整且结论不稳健 → UNKNOWN
                    is_theme_highest = None
                    theme_highest_status = "DATA_PENDING"
                    theme_highest_evidence["warning"] = "题材母体不完整且最高板结论不稳健，is_theme_highest=UNKNOWN(DATA_PENDING)"

            theme_highest_evidence["is_theme_highest"] = is_theme_highest
            theme_highest_evidence["theme_status"] = theme_highest_status

            # 构建个股数据（用于种子股识别）
            v22_stock_data = {
                "code": stock["code"],
                "name": stock["name"],
                "board": stock.get("board", 2),
                "top_concept": top_concept,
                "theme_rank": theme_rank,
                "is_theme_highest": is_theme_highest,
                "theme_highest_evidence": theme_highest_evidence,
                "seal_time": stock.get("seal_time", ""),
                "seal_time_rank_pct": _calc_seal_time_rank_pct(stock, second_board),
                "seal_amount": stock.get("seal_amount", 0),
                "seal_amount_rank_pct": _calc_seal_amount_rank_pct(stock, second_board),
                "is_not_late_seal": _is_not_late_seal(stock.get("seal_time", "")),
            }

            # 个股级别周期状态识别（传入个股数据用于种子股识别）
            try:
                v22_stock_result = detect_cycle_state(
                    market_data=v22_market_data, stock=v22_stock_data,
                    rating=grade, market_score=market_env["total"])
            except Exception as exc:
                v22_stock_result = {"status":"ERROR", "error":str(exc), "error_type":type(exc).__name__}


        # V2.3：数据质量评级
        try:
            from scoring.data_quality import calc_data_quality
            data_quality_result = calc_data_quality({
                "seal_time": stock.get("seal_time", ""),
                "seal_amount": stock.get("seal_amount", 0),
                "turnover": stock.get("turnover", 0),
                "theme_rank": theme_rank if 'theme_rank' in dir() else None,
                "amount": stock.get("volume", 0),
            })
        except Exception as exc:
            data_quality_result = {
                "score": None, "missing_fields": ["quality_evaluation_error"],
                "level": "待证据", "status":"ERROR", "warning": str(exc),
                "error_type":type(exc).__name__,
            }

        # V2.3 Phase1 v3.1: 决策数据状态检查
        # 关键评分输入不足时，不生成正式最终分/评级/权限
        try:
            from scoring.data_quality import decision_data_status
            decision_status = decision_data_status(
                stock_data={
                    "close": stock.get("close"),  # P02A: None表示缺失，不再默认0
                    "amount_cny": stock.get("volume"),  # P03A R3.1 V4: 移除默认0，缺失时None
                    "turnover_pct": stock.get("turnover"),  # P03A R3.1 V4: 移除默认0
                    "consecutive_limit_count": stock.get("board"),  # P03A R3.1 V4: 移除默认2
                    "open_break_count": stock.get("open_count"),  # P03A R3.1 V4: 炸板次数纳入必需检查
                    "first_seal_time": stock.get("seal_time"),
                    "close_seal_amount_cny": stock.get("seal_amount"),  # P03A R3.1 V4: 移除默认0
                },
                market_data=v22_market_data if 'v22_market_data' in dir() else None,
                theme_data={
                    "industry_status": "VALID" if stock.get("industry") else "DATA_PENDING",
                    "trade_theme_status": "DATA_PENDING",  # 免费公开数据源未取得当日TRADE_THEME，可用INDUSTRY+STATIC_CONCEPT
                    "static_concept_status": "UNVERIFIED_HISTORICAL",
                },
                seed_data={
                    "theme_rank": theme_rank if 'theme_rank' in dir() else None,
                    "is_theme_highest": is_theme_highest,
                    "seal_time_rank_pct": _calc_seal_time_rank_pct(stock, second_board),
                    "seal_amount_rank_pct": _calc_seal_amount_rank_pct(stock, second_board),
                } if is_theme_highest is not None else None,
            )
        except Exception as e:
            # P03A R3.1 V4: 校验异常不能归到READY/VALID，必须保留错误
            decision_status = {"score_status": "ERROR", "missing_critical_fields": ["decision_data_status_exception"], "blocking_fields": [], "error": str(e), "error_type": type(e).__name__}

        if not isinstance(decision_status, dict):
            decision_status = {"score_status":"ERROR","missing_critical_fields":["validator_result_type"],"blocking_fields":["validator_result_type"]}
        decision_status = dict(decision_status)
        missing = list(decision_status.get("missing_critical_fields", []))
        for key in ("highest_board","rate_23","open_board_rate","high_board_fail_rate","prior_limitup_continue_rate"):
            if v22_market_data.get(key) is None:
                missing.append("market." + key)
        for key, mod in modules.items():
            if mod.get("total") is None:
                missing.append("modules." + key)
        if data_quality_result.get("status") == "ERROR":
            missing.append("data_quality.ERROR")
        decision_status["missing_critical_fields"] = list(dict.fromkeys(missing))
        decision_status["blocking_fields"] = list(dict.fromkeys(list(decision_status.get("blocking_fields", [])) + missing))
        if missing and decision_status.get("score_status") == "VALID":
            decision_status["score_status"] = "DATA_PENDING"

        # V2.3 Phase1 v3.1: 如果数据不足，覆盖final_score/grade为None
        legacy_score = final_score  # 保留原旧算法结果供对照
        legacy_grade = grade
        legacy_grade_desc = grade_desc

        # P02B: 隔离研究与正式输出
        # 当前新策略仍NOT_IMPLEMENTED/NOT_ENABLED
        # 输入齐备但策略未启用时，score_status=RESEARCH_ONLY
        # 输入不足为DATA_PENDING
        # 校验异常按已有INVALID/ERROR传播
        strategy_status = "NOT_ENABLED"
        input_status = "READY"
        score_status_reason = ""

        # P03A R3.1 V3: 数据不足时即使有旧否决，input_status也应该是INSUFFICIENT
        # 已知旧否决不掩盖未知完整研究分，legacy_score为None时不转0
        # P03A R3.1 V5: ERROR/INVALID状态也必须传播，不能只识别DATA_PENDING
        decision_score_status = decision_status.get("score_status", "VALID")
        is_data_pending = decision_score_status != "VALID"
        missing_fields = decision_status.get("missing_critical_fields", [])
        decision_error = decision_status.get("error")

        if is_data_pending:
            # No current complete score/rating survives failed validation.
            raw_score = None
            legacy_score = None
            legacy_grade = None
            legacy_grade_desc = None
            buy_reasons = []
            final_score = None
            grade = None
            grade_desc = None
            input_status = "INSUFFICIENT"
            if vetoed:
                # 数据不足 + 旧否决：保留否决事实，但完整研究分未知不转0
                score_status = "DATA_PENDING_WITH_VETO"
                score_status_reason = "关键输入数据缺失: " + ", ".join(missing_fields) + "; 同时存在旧模型一票否决（否决事实保留，完整研究分未知不转0）"
                # P03A R3.1 V3: 数据不足时，legacy_score直接设为None，不转0
                legacy_score = None
                legacy_grade = None
                legacy_grade_desc = None
            else:
                # 仅数据不足
                score_status = "DATA_PENDING" if decision_score_status != "ERROR" else "ERROR"
                score_status_reason = "关键输入数据缺失: " + ", ".join(missing_fields)
                if decision_error:
                    score_status_reason += "; 校验器异常: " + str(decision_error)
        elif vetoed:
            # 输入齐备 + 一票否决（旧模型研究结果）
            score_status = "RESEARCH_ONLY"
            score_status_reason = "旧模型研究结果：一票否决"
            # 正式分/评级不生成
            final_score = None
            grade = None
            grade_desc = None
        else:
            # 输入齐备但策略未启用 → RESEARCH_ONLY
            score_status = "RESEARCH_ONLY"
            score_status_reason = "输入齐备，新策略未启用，显示旧模型研究分（未验证）"
            # 正式分/评级不生成
            final_score = None
            grade = None
            grade_desc = None

        results.append({
            "code": stock["code"],
            "name": stock["name"],
            "concepts": stock.get("concepts", []),
            "limit_up_reason": stock.get("limit_up_reason"),
            "concept_source": stock.get("concept_source"),
            "top_concept": top_concept,
            "market_type": stock["market_type"],
            "seal_time": stock["seal_time"],
            "seal_time_fmt": _fmt_time(stock["seal_time"]),
            "seal_amount": stock["seal_amount"],
            "seal_amount_fmt": _fmt_amount(stock["seal_amount"]),
            "turnover": stock["turnover"],
            "open_count": stock["open_count"],
            "volume": stock["volume"],
            "float_mv": stock.get("float_mv", 0),
            # P02A: 收盘价（从涨停池"最新价"提取）
            "close": stock.get("close"),

            # 评分模块（V2.1六大模块）
            "modules": modules,
            "raw_score": raw_score,
            "known_subtotal": known_subtotal,
            "known_subtotal_note": "已知模块小计，非完整研究分，不用于评级或排名",
            "legacy_unvalidated": True,
            "risk_deduct": risk_deduct,
            "final_score": final_score,
            "grade": grade,
            "grade_desc": grade_desc,
            "confidence": confidence,
            "confidence_pct": round(confidence_pct * 100, 1),

            # 否决
            "vetoed": vetoed,
            "veto_reason": veto_reason,

            # 理由
            "buy_reasons": buy_reasons,
            "skip_reasons": skip_reasons,
            "risks": [{"level": lv, "desc": ds} for lv, ds in risks],
            "intraday_conditions": intraday,

            # V2.1：竞价反馈预留字段
            "next_day_feedback": next_day_feedback,

            # V2.1：模型版本
            "model_version": "V2.3",

            # V2.3：统一题材排名
            "theme_rank": theme_rank if 'theme_rank' in dir() else None,

            # V2.3：数据质量评级
            "data_quality": data_quality_result,

            # V2.3 Phase1 v3.1: 决策数据状态
            "score_status": score_status,
            "score_status_reason": score_status_reason,
            # P02B: 输入状态和策略状态隔离
            "input_status": input_status,
            "strategy_status": strategy_status,
            "strategy_note": "新Core2/Seed策略尚未实现，当前仅显示旧模型研究分（未验证）",
            # P03A R1: 显式声明新正式分/评级/权限为null，不继承旧v22
            "final_score": final_score,
            "grade": grade,
            "grade_desc": grade_desc,
            "permission": None,  # 新正式权限未生成，不继承旧v22
            "permission_note": "新策略未启用，正式交易权限未生成",
            # 旧模型研究分（未验证）
            "legacy_score": legacy_score,
            "legacy_grade": legacy_grade,
            "legacy_grade_desc": legacy_grade_desc,
            # P03A R1: close元数据（来源列名、来源状态、实际数据日期、时点）
            "close_meta": {
                "value": stock.get("close"),
                "source_field": stock.get("close_source_field", "最新价/收盘价"),
                # P03A R3.1 V5: 使用close_status，bool/NaN/inf/负数不会被认为是VALID
                "source_status": stock.get("close_status", stock.get("close_source_status", "MISSING")),
                "source_date": stock.get("close_source_date", None),  # 实际数据日期，不伪造观察日
                "snapshot_time": stock.get("close_snapshot_time", None),
                "note": "收盘价来自涨停池最新价字段，实际数据日期未知时为null；bool/NaN/inf/负数标记为INVALID"
            },
            "decision_data_status": decision_status,
            # P02A: 阻断字段（从decision_data_status提取，方便前端直接使用）
            "blocking_fields": decision_status.get("blocking_fields", []),
            "missing_critical_fields": decision_status.get("missing_critical_fields", []),

            # V2.2：周期状态识别（个股级别）
            "v22": v22_stock_result,
        })

    for result in results:
        screening = (candidate_filter_evidence or {}).get(result["code"], {
            "status":"UNKNOWN", "reason":"两日开盘/收盘涨停证据未提供", "rule":"TWO_OPEN_LIMIT_DAYS"})
        result["candidate_screening"] = screening
        result["candidate_status"] = screening.get("status", "UNKNOWN")
        result["legacy_cycle_diagnostic"] = result.pop("v22", None)
        result["v22"] = None
        result["five_day_cycle_status"] = "PAUSED_BY_USER"
        if screening.get("status") == "EXCLUDED":
            result["exclusion_reason"] = screening.get("reason")
            result["legacy_before_candidate_filter"] = {"score":result["legacy_score"],"grade":result["legacy_grade"],"status":"UNVALIDATED_DIAGNOSTIC_ONLY"}
            result["raw_score"] = None
            result["legacy_score"] = None
            result["legacy_grade"] = None
            result["legacy_grade_desc"] = None
            result["score_status"] = "EXCLUDED"
        result["candidate_eligible"] = screening.get("status") == "ALLOWED_BY_THIS_RULE" and result["input_status"] == "READY"

    # 按旧模型研究分降序排序（P02B: final_score为None，使用legacy_score排序）
    # P03A R3.1: raw_score为None时也能正常排序
    results.sort(key=lambda x: (
        -x["legacy_score"] if x["legacy_score"] is not None else 999,
        -x["raw_score"] if x["raw_score"] is not None else 999
    ))

    for i, r in enumerate(results):
        r["rank"] = i + 1 if r["legacy_score"] is not None and r.get("candidate_eligible") is True else None

    return results


# ============================================================
# 测试入口
# ============================================================

if __name__ == "__main__":
    import sys
    from collection.data_fetcher import _limit_up_pool, _open_board_pool

    target = sys.argv[1] if len(sys.argv) > 1 else "20260904"

    print(f"=== 二进三决策模型 V2.1 测试 ({target}) ===")

    limit_up = _limit_up_pool(target)
    open_board = _open_board_pool(target)

    results = evaluate_three_board(
        limit_up_df=limit_up,
        open_board_df=open_board,
        date=target,
        rate_23=17.65,
        highest_board=5,
    )

    print(f"\n二板股数量: {len(results)}")
    for r in results:
        print(f"\n{'='*60}")
        print(f"排名{r['rank']}: {r['name']}({r['code']}) 「{r['top_concept']}」")
        print(f"  原始分: {r['raw_score']}  风险扣分: {r['risk_deduct']}  最终: {r['final_score']}")
        print(f"  评级: {r['grade']}({r['grade_desc']})  置信度: {r['confidence']}({r['confidence_pct']}%)")
        if r['vetoed']:
            print(f"  ⚠ 一票否决: {r['veto_reason']}")
        print(f"  封板: {r['seal_time_fmt']}  封单: {r['seal_amount_fmt']}  换手: {r['turnover']:.1f}%  炸板: {r['open_count']}次")
        print(f"\n  【模块评分】")
        for mod_name, mod in r['modules'].items():
            print(f"    {mod_name}: {mod['total']}/{mod['max']}")
        print(f"\n  【打板理由/个股优势】")
        for i, reason in enumerate(r['buy_reasons'], 1):
            print(f"    {i}. {reason}")
        print(f"\n  【放弃/风险理由】")
        for i, reason in enumerate(r['skip_reasons'], 1):
            print(f"    {i}. {reason}")
