# -*- coding: utf-8 -*-

"""
============================================================
V2.3 Phase1 v3.1 数据质量检测模块

核心原则：
  不知道 ≠ 很差，也 ≠ 中性表现。
  关键字段缺失时，不生成正式最终分。
  （neutral_score已删除，不得重新引入50%中性补分）

功能：
  1. 封板时间有效性检测（A股真实交易时段）
  2. 封板资金有效性检测
  3. 换手率有效性检测
  4. 题材排名有效性检测
  5. 数据质量评分（100分制）
  6. 缺失字段清单
  7. 决策数据状态检查（decision_data_status）
============================================================
"""

from __future__ import annotations
from input_contracts import number, integer
import numpy as np


# ============================================================
# 封板时间检测
# ============================================================

# 以下值全部视为缺失
INVALID_SEAL_TIMES = {None, 0, "0", "000000", "235959", "999999", ""}


def is_seal_time_valid(seal_time) -> bool:
    """Validate the existing time-window contract, without coercing booleans/containers."""
    if isinstance(seal_time, (bool, np.bool_)) or seal_time is None:
        return False
    if isinstance(seal_time, (int, np.integer)):
        text=str(int(seal_time)).zfill(6)
    elif isinstance(seal_time,str):
        text=seal_time.strip()
    else:
        return False
    if len(text)!=6 or not text.isdigit() or text in {"000000","235959","999999"}:
        return False
    h,m,s=int(text[:2]),int(text[2:4]),int(text[4:])
    if h>23 or m>59 or s>59:
        return False
    total=h*3600+m*60+s
    return 33900<=total<=33959 or 34200<=total<=41400 or 46800<=total<=54000




def is_not_late_seal(seal_time) -> bool:
    """
    检测是否非尾盘板（14:00以前封板）
    """
    if not is_seal_time_valid(seal_time):
        return False
    try:
        hour = int(str(seal_time)[:2])
        minute = int(str(seal_time)[2:4])
        return hour < 14 or (hour == 14 and minute == 0)
    except (ValueError, IndexError):
        return False


# ============================================================
# 封板资金检测
# ============================================================

def is_seal_amount_valid(seal_amount) -> bool:
    """Retain the original threshold; reject boolean/nonfinite values."""
    v=number(seal_amount)
    return v is not None and v >= 1000




# ============================================================
# 换手率检测
# ============================================================

def is_turnover_valid(turnover) -> bool:
    """Retain the original threshold; reject boolean/nonfinite values."""
    v=number(turnover)
    return v is not None and v > 0




# ============================================================
# 题材排名检测
# ============================================================

def is_theme_rank_valid(theme_rank) -> bool:
    """Retain the original threshold; reject boolean/nonfinite values."""
    v=integer(theme_rank)
    return v is not None and v > 0




# ============================================================
# 成交额检测
# ============================================================

def is_amount_valid(amount) -> bool:
    """Retain the original threshold; reject boolean/nonfinite values."""
    v=number(amount)
    return v is not None and v >= 10000




# ============================================================
# 数据质量评分
# ============================================================

# 各字段缺失扣分
QUALITY_DEDUCTIONS = {
    "seal_time": 20,
    "seal_amount": 20,
    "turnover": 20,
    "theme_rank": 20,
    "amount": 20,
}


def calc_data_quality(stock: dict) -> dict:
    """
    计算个股数据质量评分

    输入：
      stock: 个股数据字典

    输出：
      {
        "score": 0-100,
        "missing_fields": ["seal_amount", ...],
        "seal_time_valid": bool,
        "seal_amount_valid": bool,
        "turnover_valid": bool,
        "theme_rank_valid": bool,
        "amount_valid": bool,
        "level": "高/中/低",
        "warning": "评分可信度下降" or ""
      }
    """
    checks = {
        "seal_time": is_seal_time_valid(stock.get("seal_time")),
        "seal_amount": is_seal_amount_valid(stock.get("seal_amount")),
        "turnover": is_turnover_valid(stock.get("turnover")),
        "theme_rank": is_theme_rank_valid(stock.get("theme_rank") or stock.get("concept_rank")),
        "amount": is_amount_valid(stock.get("amount") or stock.get("volume")),
    }

    score = 100
    missing_fields = []
    for field, valid in checks.items():
        if not valid:
            score -= QUALITY_DEDUCTIONS.get(field, 20)
            missing_fields.append(field)

    score = max(0, score)

    # 质量等级
    if score >= 80:
        level = "高"
        warning = ""
    elif score >= 60:
        level = "中"
        warning = ""
    else:
        level = "低"
        warning = "⚠ 评分可信度下降"

    return {
        "score": score,
        "missing_fields": missing_fields,
        "seal_time_valid": checks["seal_time"],
        "seal_amount_valid": checks["seal_amount"],
        "turnover_valid": checks["turnover"],
        "theme_rank_valid": checks["theme_rank"],
        "amount_valid": checks["amount"],
        "level": level,
        "warning": warning,
    }


# ============================================================
# 缺失值处理规则（V2.3 Phase1 v3.1）
# ============================================================
# 关键数据不足时：final_score = null, score_status = DATA_PENDING
# 不再使用"缺失=满分50%中性分"来生成看似精确的最终成绩
# neutral_score()函数已删除，不得进入任何生产评分调用链


# ============================================================
# 决策数据状态检查（V2.3 Phase1 v3.1）
# ============================================================

def decision_data_status(stock_data: dict, market_data: dict = None,
                         theme_data: dict = None, seed_data: dict = None) -> dict:
    """
    检查决策所需的关键数据是否充足。

    检查维度：
      1. 评分必需行情字段（close/amount/turnover/board等）
      2. 市场cohort状态（rate_23/high_board_fail_rate等）
      3. 当前使用题材证据状态（INDUSTRY/TRADE_THEME/STATIC_CONCEPT）
      4. Seed必要字段状态（theme_rank/is_theme_highest/seal_time_rank等）

    返回：
      {
        "score_status": "VALID" | "DATA_PENDING",
        "missing_critical_fields": [...],
        "checks": {...}
      }

    关键输入不足时：
      final_score = None, grade = None, permission = None
      不得继续产生可交易的正式评级。
    """
    missing_fields = []
    checks = {}

    # P03A R1: 统一数值有效性检查函数
    # 区分不同字段的契约：close必须正有限，比例可以是0，涨幅可以是负值
    def _is_valid_number(val, field_name="", require_positive=False, allow_zero=True, allow_negative=True):
        """检查数值是否有效，区分字段契约"""
        import math
        # None = 缺失
        if val is None:
            return False
        # bool = 无效（True会变成1.0，False会变成0.0）
        if isinstance(val, (bool, np.bool_)):
            return False
        # 空字符串 = 无效
        if isinstance(val, str) and val.strip() == "":
            return False
        # 尝试转换为float
        try:
            val_float = float(val)
        except (ValueError, TypeError):
            return False
        # NaN/inf = 无效
        if not math.isfinite(val_float):
            return False
        # 必须为正数（如close）
        if require_positive and val_float <= 0:
            return False
        # 不允许0（如封单金额，涨停股应该有封单）
        if not allow_zero and val_float == 0:
            return False
        # 不允许负值（如换手率、成交量）
        if not allow_negative and val_float < 0:
            return False
        return True

    # 1. 评分必需行情字段
    # P03A R1: 区分字段契约，close必须正有限，其他字段按各自契约
    required_market_fields = {
        "close": {"require_positive": True, "allow_zero": False, "allow_negative": False},
        "amount_cny": {"require_positive": False, "allow_zero": False, "allow_negative": False},
        "turnover_pct": {"require_positive": False, "allow_zero": True, "allow_negative": False},
        "consecutive_limit_count": {"require_positive": False, "allow_zero": False, "allow_negative": False},
        # P03A R3.1 V4: 炸板次数参与评分，必须纳入必需检查
        # 有效0保留（未炸板），None/bool/NaN/inf/负数无效
        "open_break_count": {"require_positive": False, "allow_zero": True, "allow_negative": False},
    }
    market_field_status = {}
    for field, contract in required_market_fields.items():
        val = stock_data.get(field)
        if isinstance(val, dict):
            valid = val.get("status") == "VALID" and _is_valid_number(val.get("value"), field, **contract)
        else:
            valid = _is_valid_number(val, field, **contract)
        market_field_status[field] = valid
        if not valid:
            missing_fields.append(f"stock.{field}")
    checks["market_fields"] = market_field_status

    # 2. 封板质量字段（二进三评分必需）
    # P03A R1: first_seal_time按时间契约检查，close_seal_amount_cny必须正数
    required_seal_fields = {
        "first_seal_time": {"type": "seal_time"},
        "close_seal_amount_cny": {"type": "positive_number"},
    }
    seal_field_status = {}
    for field, contract in required_seal_fields.items():
        val = stock_data.get(field)
        if isinstance(val, dict):
            valid = val.get("status") == "VALID" and (is_seal_time_valid(val.get("value")) if contract["type"]=="seal_time" else _is_valid_number(val.get("value"),field,require_positive=True,allow_zero=False,allow_negative=False))
        elif contract["type"] == "seal_time":
            # 封板时间按时间有效性检查
            valid = is_seal_time_valid(val)
        else:
            # 封单金额必须是正数
            valid = _is_valid_number(val, field, require_positive=True, allow_zero=False, allow_negative=False)
        seal_field_status[field] = valid
        if not valid:
            missing_fields.append(f"stock.{field}")
    checks["seal_fields"] = seal_field_status

    # 3. 市场cohort状态
    # P02B: 正确区分有效0和缺失，禁止bool和非有限/越界数
    if market_data:
        import math
        cohort_status = {}
        for key in ["rate_23", "high_board_fail_rate", "prior_limitup_continue_rate"]:
            val = market_data.get(key)
            # None = 缺失
            if val is None:
                cohort_status[key] = False
                missing_fields.append(f"market.{key}")
                continue
            # bool = 无效（True会变成1.0）
            if isinstance(val, (bool, np.bool_)):
                cohort_status[key] = False
                missing_fields.append(f"market.{key}")
                continue
            # 非有限数 = 无效
            try:
                val_float = float(val)
                if not math.isfinite(val_float):
                    cohort_status[key] = False
                    missing_fields.append(f"market.{key}")
                    continue
                # 越界（0~100）= 无效
                if val_float < 0 or val_float > 100:
                    cohort_status[key] = False
                    missing_fields.append(f"market.{key}")
                    continue
                # 有效0或正数 = 有效
                cohort_status[key] = True
            except (ValueError, TypeError):
                cohort_status[key] = False
                missing_fields.append(f"market.{key}")
        checks["market_cohorts"] = cohort_status

    # 4. 题材证据状态
    if theme_data:
        theme_status = {}
        # INDUSTRY应该VALID
        industry_valid = theme_data.get("industry_status") == "VALID"
        theme_status["industry"] = industry_valid
        if not industry_valid:
            missing_fields.append("theme.industry")
        # TRADE_THEME可以是DATA_PENDING（不阻塞，但标记）
        trade_theme_status = theme_data.get("trade_theme_status", "DATA_PENDING")
        theme_status["trade_theme"] = trade_theme_status
        # STATIC_CONCEPT应该有数据
        static_concept_valid = theme_data.get("static_concept_status") in ["VALID", "UNVERIFIED_HISTORICAL"]
        theme_status["static_concept"] = static_concept_valid
        if not static_concept_valid:
            missing_fields.append("theme.static_concept")
        checks["theme_evidence"] = theme_status

    # 5. Seed必要字段状态
    if seed_data:
        seed_status = {}
        for key in ["theme_rank", "is_theme_highest", "seal_time_rank_pct", "seal_amount_rank_pct"]:
            val = seed_data.get(key)
            if val is not None and val != "":
                seed_status[key] = True
            else:
                seed_status[key] = False
                missing_fields.append(f"seed.{key}")
        checks["seed_fields"] = seed_status

    # 最终判定
    # 注意：TRADE_THEME为DATA_PENDING不阻塞评分（可用INDUSTRY+STATIC_CONCEPT）
    # 但封板质量字段和行情字段必须VALID
    critical_blocking_fields = [f for f in missing_fields
                                 if not f.startswith("theme.trade_theme")
                                 ]  # market cohort可以为0（真实值）

    if critical_blocking_fields:
        score_status = "DATA_PENDING"
    else:
        score_status = "VALID"

    return {
        "score_status": score_status,
        "missing_critical_fields": missing_fields,
        "blocking_fields": critical_blocking_fields,
        "checks": checks,
    }

