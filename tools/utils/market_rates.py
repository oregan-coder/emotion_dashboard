# -*- coding: utf-8 -*-
"""
P03A: 统一市场比例定义模块

四种比例严格区分，禁止一值多义：
1. failed_limitup_rate     全市场炸板率
2. high_board_fail_rate    高位晋级失败率
3. prior_limitup_continue_rate  昨日涨停续板率
4. two_to_three_rate       二进三晋级率

每个比例输出：value, numerator, denominator, numerator_codes, denominator_codes,
formula, provider, status, unit
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class MarketRate:
    """市场比例标准结构"""
    name: str
    value: Optional[float] = None  # 百分比，如19.57表示19.57%
    numerator: int = 0
    denominator: int = 0
    numerator_codes: List[str] = field(default_factory=list)
    denominator_codes: List[str] = field(default_factory=list)
    formula: str = ""
    provider: str = ""
    status: str = "MISSING"  # VALID / MISSING / ERROR / N_A
    unit: str = "%"
    observation_date: str = ""
    prior_date: str = ""
    note: str = ""

    def to_dict(self):
        d = {
            "name": self.name,
            "value": self.value,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "numerator_codes": self.numerator_codes,
            "denominator_codes": self.denominator_codes,
            "formula": self.formula,
            "provider": self.provider,
            "status": self.status,
            "unit": self.unit,
            "observation_date": self.observation_date,
            "prior_date": self.prior_date,
            "note": self.note,
        }
        # P03A R3.1: 包含动态挂的threshold和threshold_status，避免序列化丢失审批状态
        if hasattr(self, "threshold"):
            d["threshold"] = self.threshold
        if hasattr(self, "threshold_status"):
            d["threshold_status"] = self.threshold_status
        return d


def calc_failed_limitup_rate(
    limit_up_codes: List[str],
    failed_limit_up_codes: List[str],
    observation_date: str = "",
    provider: str = "akshare_stock_zt_pool_em",
) -> MarketRate:
    """
    全市场炸板率

    定义：当日曾触及涨停但收盘未封住的股票，占收盘涨停+封板未遂的比例
    公式：failed_limitup_count / (limit_up_count + failed_limitup_count) * 100
    母体：当日全部曾涨停股票（收盘涨停 + 封板未遂）
    分子：当日封板未遂（炸板）股票
    """
    rate = MarketRate(
        name="failed_limitup_rate",
        formula="炸板数 / (涨停数 + 炸板数) * 100",
        provider=provider,
        observation_date=observation_date,
    )

    if not limit_up_codes and not failed_limit_up_codes:
        rate.status = "MISSING"
        rate.note = "涨停池和炸板池均为空"
        return rate

    denominator_set = set(limit_up_codes) | set(failed_limit_up_codes)
    numerator_set = set(failed_limit_up_codes)

    rate.denominator = len(denominator_set)
    rate.numerator = len(numerator_set)
    rate.denominator_codes = sorted(denominator_set)
    rate.numerator_codes = sorted(numerator_set)

    if rate.denominator > 0:
        rate.value = round(rate.numerator / rate.denominator * 100, 4)
        rate.status = "VALID"
    else:
        rate.status = "N_A"
        rate.note = "分母为0"

    return rate


def calc_high_board_fail_rate(
    prior_high_board_codes: List[str],
    today_continue_codes: List[str],
    observation_date: str = "",
    prior_date: str = "",
    high_board_threshold: int = 4,  # V6: 用户已批准高位>=4板
    provider: str = "akshare_stock_zt_pool_em",
) -> MarketRate:
    """
    高位晋级失败率

    定义：昨日高位股（>=threshold板）中今天未成功续板的比例
    公式：(昨日高位股数 - 今日续板数) / 昨日高位股数 * 100
    母体：昨日全部高位股（>=threshold板）
    分子：昨日高位股中今日未成功续板的股票

    【审批状态】V6: 用户已批准高位>=4板规则（approved_rules.json）。
    默认threshold=4，threshold_status=USER_APPROVED。
    smash_engine.py内部也使用>=4板，现已统一。
    """
    rate = MarketRate(
        name="high_board_fail_rate",
        formula=f"(昨日{high_board_threshold}板及以上股数 - 今日续板数) / 昨日{high_board_threshold}板及以上股数 * 100",
        provider=provider,
        observation_date=observation_date,
        prior_date=prior_date,
    )
    rate.threshold = high_board_threshold
    rate.threshold_status = "USER_APPROVED" if high_board_threshold == 4 else "CUSTOM"

    if not prior_high_board_codes:
        rate.status = "MISSING"
        rate.note = f"昨日{high_board_threshold}板及以上股票为空"
        return rate

    denominator_set = set(prior_high_board_codes)
    continue_set = set(today_continue_codes) & denominator_set
    fail_set = denominator_set - continue_set

    rate.denominator = len(denominator_set)
    rate.numerator = len(fail_set)
    rate.denominator_codes = sorted(denominator_set)
    rate.numerator_codes = sorted(fail_set)

    if rate.denominator > 0:
        rate.value = round(rate.numerator / rate.denominator * 100, 4)
        rate.status = "VALID"
    else:
        rate.status = "N_A"
        rate.note = "分母为0"

    return rate


def calc_prior_limitup_continue_rate(
    prior_limit_up_codes: List[str],
    today_limit_up_codes: List[str],
    observation_date: str = "",
    prior_date: str = "",
    provider: str = "akshare_stock_zt_pool_em",
) -> MarketRate:
    """
    昨日涨停续板率

    定义：昨日涨停股票中今日继续涨停的比例
    公式：昨日涨停且今日涨停数 / 昨日涨停总数 * 100
    母体：昨日全部涨停股票
    分子：昨日涨停且今日继续涨停的股票
    """
    rate = MarketRate(
        name="prior_limitup_continue_rate",
        formula="昨日涨停且今日涨停数 / 昨日涨停总数 * 100",
        provider=provider,
        observation_date=observation_date,
        prior_date=prior_date,
    )

    if not prior_limit_up_codes:
        rate.status = "MISSING"
        rate.note = "昨日涨停股票为空"
        return rate

    denominator_set = set(prior_limit_up_codes)
    numerator_set = set(today_limit_up_codes) & denominator_set

    rate.denominator = len(denominator_set)
    rate.numerator = len(numerator_set)
    rate.denominator_codes = sorted(denominator_set)
    rate.numerator_codes = sorted(numerator_set)

    if rate.denominator > 0:
        rate.value = round(rate.numerator / rate.denominator * 100, 4)
        rate.status = "VALID"
    else:
        rate.status = "N_A"
        rate.note = "分母为0"

    return rate


def calc_two_to_three_rate(
    prior_second_board_codes: List[str],
    today_third_board_codes: List[str],
    observation_date: str = "",
    prior_date: str = "",
    provider: str = "akshare_stock_zt_pool_em",
) -> MarketRate:
    """
    二进三晋级率

    定义：昨日恰为二板的股票中，今日收盘恰为三板成功的比例
    公式：昨日二板且今日三板数 / 昨日二板总数 * 100
    母体：昨日全部恰为二板的股票
    分子：昨日二板且今日成功晋级三板的股票
    """
    rate = MarketRate(
        name="two_to_three_rate",
        formula="昨日二板且今日三板数 / 昨日二板总数 * 100",
        provider=provider,
        observation_date=observation_date,
        prior_date=prior_date,
    )

    if not prior_second_board_codes:
        rate.status = "MISSING"
        rate.note = "昨日二板股票为空"
        return rate

    denominator_set = set(prior_second_board_codes)
    numerator_set = set(today_third_board_codes) & denominator_set

    rate.denominator = len(denominator_set)
    rate.numerator = len(numerator_set)
    rate.denominator_codes = sorted(denominator_set)
    rate.numerator_codes = sorted(numerator_set)

    if rate.denominator > 0:
        rate.value = round(rate.numerator / rate.denominator * 100, 4)
        rate.status = "VALID"
    else:
        rate.status = "N_A"
        rate.note = "分母为0"

    return rate
