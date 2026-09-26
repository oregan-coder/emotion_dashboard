# -*- coding: utf-8 -*-

"""
============================================================
V2.2 周期状态识别器（Cycle State Detector）

位置：市场环境模块之上，作为特殊状态识别器（决策层）

核心思想：
  1. 市场永远大于个股
  2. 评分不等于交易（评分/评级/交易权限三套系统）
  3. 退潮期禁止接力旧周期，但允许试错新周期

输出：
  cycle_state: S1主升/S2震荡/S3退潮/S4新周期试错
  cycle_switch_score: 0-6分（周期切换指数）
  seed_stock: bool（是否为新周期种子股）
  trade_permission: P0-P5
  recommended_position: 仓位建议
  permission_reason: 权限判定原因
============================================================
"""

from __future__ import annotations

from config import (
    V22_MARKET_STATES,
    V22_CYCLE_SWITCH_CONDITIONS,
    V22_CYCLE_SWITCH_LEVELS,
    V22_SEED_DETECT_THRESHOLD,
    V22_SEED_STOCK_CONDITIONS,
    V22_TRADE_PERMISSIONS,
    V22_RATING_TO_PERMISSION,
    V22_ENV_LOW_THRESHOLD,
    V22_ENV_LOW_MAX_RATING,
    V22_SEED_RATING_BOOST,
    V22_SEED_BOOST_LEVELS,
    V22_STATE_DETECTION,
    V23_SEED_SCORE_MAX,
)


# ============================================================
# 工具函数
# ============================================================

def _compare(value, operator: str, threshold) -> bool:
    """通用比较函数"""
    if operator == ">=":
        return float(value) >= float(threshold)
    if operator == "<=":
        return float(value) <= float(threshold)
    if operator == ">":
        return float(value) > float(threshold)
    if operator == "<":
        return float(value) < float(threshold)
    if operator == "==":
        return value == threshold
    return False


def _get_switch_level(score: int) -> dict:
    """根据周期切换指数获取等级"""
    for level in V22_CYCLE_SWITCH_LEVELS:
        if level["min"] <= score <= level["max"]:
            return level
    return V22_CYCLE_SWITCH_LEVELS[-1]


# ============================================================
# 一、周期切换指数计算
# ============================================================

def calc_cycle_switch_score(market_data: dict) -> dict:
    """
    计算周期切换指数（Cycle Switch Score）

    输入 market_data 字段：
      - highest_board: 最高板数
      - board_4_count: 4板数量
      - board_3_count: 3板数量
      - rate_23: 2→3成功率（百分比）
      - open_board_rate: 炸板率（百分比）
      - has_core_2board: 是否存在核心二板（bool）
      - second_board_stocks: 二板股列表（用于判断核心二板）
      - concept_stats: 概念统计

    输出：
      - score: 0-6分
      - level: 非切换期/疑似切换期/高概率切换期
      - conditions: 每个条件的命中情况
    """
    conditions_result = []
    total_score = 0

    for cond in V22_CYCLE_SWITCH_CONDITIONS:
        field = cond["field"]
        value = market_data.get(field)

        # 特殊处理：has_core_2board 需要动态计算
        if field == "has_core_2board" and value is None:
            value = _detect_core_2board(market_data)

        if value is None:
            hit = False
            value_display = "数据缺失"
        else:
            hit = _compare(value, cond["operator"], cond["threshold"])
            value_display = value

        if hit:
            total_score += cond["score"]

        conditions_result.append({
            "id": cond["id"],
            "name": cond["name"],
            "field": field,
            "value": value_display,
            "threshold": cond["threshold"],
            "operator": cond["operator"],
            "hit": hit,
            "score": cond["score"] if hit else 0,
            "source": cond["source"]
        })

    level = _get_switch_level(total_score)

    return {
        "score": total_score,
        "level": level["level"],
        "level_color": level["color"],
        "conditions": conditions_result
    }


def _detect_core_2board(market_data: dict) -> bool:
    """
    检测是否存在核心二板
    定义：二板数量≤3 且 存在题材排名前3 且 封板资金排名前20%的二板股
    """
    second_boards = market_data.get("second_board_stocks", [])
    if not second_boards:
        return False

    # 二板数量≤3
    if len(second_boards) > 3:
        return False

    # 检查是否有核心二板
    concept_stats = market_data.get("concept_stats", {})
    for stock in second_boards:
        # 题材排名前3
        top_concept = stock.get("top_concept", "")
        concept_rank = concept_stats.get(top_concept, {}).get("rank", 999)
        if concept_rank > 3:
            continue

        # 封板资金排名前20%（简化判断：封板资金>平均）
        seal_amount = stock.get("seal_amount", 0)
        all_seal_amounts = [s.get("seal_amount", 0) for s in second_boards]
        if all_seal_amounts and seal_amount >= sorted(all_seal_amounts, reverse=True)[max(0, int(len(all_seal_amounts) * 0.2) - 1)]:
            return True

    return False


# ============================================================
# 二、市场状态识别（S1-S4）
# ============================================================

def detect_market_state(market_data: dict, switch_result: dict) -> dict:
    """
    识别市场状态（S1主升/S2震荡/S3退潮/S4新周期试错）

    优先级：S4 > S1 > S3 > S2
    （S4新周期试错期优先级最高，因为它是特殊状态）
    """
    highest_board = market_data.get("highest_board", 0)
    rate_23 = market_data.get("rate_23", 0)
    open_board_rate = market_data.get("open_board_rate", 0)
    board_3_plus = market_data.get("board_3_plus_count", 0)

    # S4: 新周期试错期（高概率切换期 + 存在核心二板）
    s4_cfg = V22_STATE_DETECTION["S4_new_cycle"]
    if (switch_result["score"] >= s4_cfg["cycle_switch_score_min"]
            and market_data.get("has_core_2board", False)):
        return {
            "state": "S4",
            "name": V22_MARKET_STATES["S4"]["name"],
            "desc": V22_MARKET_STATES["S4"]["desc"],
            "behavior": V22_MARKET_STATES["S4"]["behavior"],
            "color": "#ffc107",
            "reason": [
                f"周期切换指数{switch_result['score']}分（高概率切换期）",
                "存在核心二板",
                "老周期退潮，新周期萌芽"
            ]
        }

    # S1: 主升周期
    s1_cfg = V22_STATE_DETECTION["S1_main_up"]
    if (highest_board >= s1_cfg["highest_board_min"]
            and rate_23 >= s1_cfg["rate_23_min"]
            and open_board_rate <= s1_cfg["open_board_rate_max"]
            and board_3_plus >= s1_cfg["board_3_plus_count_min"]):
        return {
            "state": "S1",
            "name": V22_MARKET_STATES["S1"]["name"],
            "desc": V22_MARKET_STATES["S1"]["desc"],
            "behavior": V22_MARKET_STATES["S1"]["behavior"],
            "color": "#dc3545",
            "reason": [
                f"最高板{highest_board}板",
                f"2→3成功率{rate_23:.1f}%",
                f"炸板率{open_board_rate:.1f}%",
                "高标持续晋级，赚钱效应扩散"
            ]
        }

    # S3: 退潮周期
    s3_cfg = V22_STATE_DETECTION["S3_decline"]
    if (rate_23 <= s3_cfg["rate_23_max"]
            and open_board_rate >= s3_cfg["open_board_rate_min"]):
        return {
            "state": "S3",
            "name": V22_MARKET_STATES["S3"]["name"],
            "desc": V22_MARKET_STATES["S3"]["desc"],
            "behavior": V22_MARKET_STATES["S3"]["behavior"],
            "color": "#6c757d",
            "reason": [
                f"2→3成功率{rate_23:.1f}%（过低）",
                f"炸板率{open_board_rate:.1f}%（过高）",
                "高标断板，中位股崩溃"
            ]
        }

    # S2: 震荡周期（默认）
    return {
        "state": "S2",
        "name": V22_MARKET_STATES["S2"]["name"],
        "desc": V22_MARKET_STATES["S2"]["desc"],
        "behavior": V22_MARKET_STATES["S2"]["behavior"],
        "color": "#17a2b8",
        "reason": [
            f"最高板{highest_board}板",
            f"2→3成功率{rate_23:.1f}%",
            f"炸板率{open_board_rate:.1f}%",
            "晋级率正常，赚钱效应一般"
        ]
    }


# ============================================================
# 三、新周期种子股识别
# ============================================================

def detect_seed_stock(stock: dict, market_data: dict, switch_result: dict) -> dict:
    """
    识别新周期种子股（V2.3版本）

    V2.3新规则：
      必须满足：A（题材前3）+ B（题材最高板）
      进攻性条件：满足任意一项 C（封板时间前20%）或 D（封板资金前20%）
      公式：seed = A and B and (C or D)
      E（非尾盘板）为加分项，不影响种子资格

    仅在 cycle_switch_score >= 5 时启动
    输出 seed_score（0-10分）：A+3, B+3, C+2, D+2, E+1

    输入 stock 字段：
      - code, name, board
      - top_concept: 最强题材
      - theme_rank: 题材排名（V2.3统一字段）
      - is_theme_highest: 是否为题材最高板
      - seal_time: 封板时间（HHMMSS）
      - seal_time_rank_pct: 封板时间排名百分比
      - seal_amount: 封板资金
      - seal_amount_rank_pct: 封板资金排名百分比
      - is_not_late_seal: 是否非尾盘板
    """
    # 仅在高概率切换期启动
    if switch_result["score"] < V22_SEED_DETECT_THRESHOLD:
        return {
            "is_seed": False,
            "seed_score": 0,
            "seed_score_max": V23_SEED_SCORE_MAX,
            "reason": f"周期切换指数{switch_result['score']}分，低于启动阈值{V22_SEED_DETECT_THRESHOLD}分",
            "conditions": [],
            "audit_log": {},
            "false_kill_warning": "",
        }

    conditions_result = []
    seed_score = 0
    audit_log = {}

    # 逐项检测
    for cond in V22_SEED_STOCK_CONDITIONS:
        field = cond["field"]
        value = stock.get(field)

        if value is None:
            hit = False
            value_display = "数据缺失"
            is_data_missing = True
        else:
            hit = _compare(value, cond["operator"], cond["threshold"])
            value_display = value
            is_data_missing = False

        # 累计种子评分
        weight = cond.get("score_weight", 0)
        if hit:
            seed_score += weight

        conditions_result.append({
            "id": cond["id"],
            "name": cond["name"],
            "field": field,
            "value": value_display,
            "threshold": cond["threshold"],
            "operator": cond["operator"],
            "hit": hit,
            "required": cond["required"],
            "score_weight": weight,
            "is_data_missing": is_data_missing,
            "source": cond["source"]
        })

        # 审计日志
        audit_log[cond["id"]] = {
            "hit": hit,
            "value": value_display,
            "threshold": f"{cond['operator']} {cond['threshold']}",
            "is_data_missing": is_data_missing,
        }

    seed_score = min(seed_score, V23_SEED_SCORE_MAX)

    # V2.3判定逻辑：A and B and (C or D)
    cond_a = next(c for c in conditions_result if c["id"] == "A")
    cond_b = next(c for c in conditions_result if c["id"] == "B")
    cond_c = next(c for c in conditions_result if c["id"] == "C")
    cond_d = next(c for c in conditions_result if c["id"] == "D")
    cond_e = next(c for c in conditions_result if c["id"] == "E")

    a_hit = cond_a["hit"]
    b_hit = cond_b["hit"]
    c_hit = cond_c["hit"]
    d_hit = cond_d["hit"]
    e_hit = cond_e["hit"]

    is_seed = a_hit and b_hit and (c_hit or d_hit)

    # 生成判定原因
    reason_parts = []
    if is_seed:
        reason_parts.append("满足A+B+(C或D)")
        if c_hit and d_hit:
            reason_parts.append("C和D均命中（进攻性强）")
        elif c_hit:
            reason_parts.append("C命中（封板时间靠前）")
        elif d_hit:
            reason_parts.append("D命中（封板资金靠前）")
        if e_hit:
            reason_parts.append("额外满足E（非尾盘板）")
    else:
        failed = []
        if not a_hit:
            if cond_a["is_data_missing"]:
                failed.append("A数据缺失（题材排名未获取）")
            else:
                failed.append(f"A未达标（题材排名{cond_a['value']}，需≤3）")
        if not b_hit:
            if cond_b["is_data_missing"]:
                failed.append("B数据缺失")
            else:
                failed.append("B未达标（非题材最高板）")
        if not (c_hit or d_hit):
            c_msg = "C数据缺失" if cond_c["is_data_missing"] else f"C未达标（封板时间排名{cond_c['value']}%，需≤20%）"
            d_msg = "D数据缺失" if cond_d["is_data_missing"] else f"D未达标（封板资金排名{cond_d['value']}%，需≤20%）"
            failed.append(f"C和D均未达标（{c_msg}；{d_msg}）")
        reason_parts.append(f"未满足: {'; '.join(failed)}")

    # 误杀检查器
    false_kill_warning = ""
    if (not is_seed
            and a_hit
            and b_hit
            and switch_result["score"] >= V22_SEED_DETECT_THRESHOLD):
        # 满足A+B+切换期，但未进入种子股
        if not (c_hit or d_hit):
            false_kill_warning = (
                "⚠ 疑似误杀：满足题材前三+题材最高板+切换期，"
                "但C/D进攻性条件未达标。请检查封板时间/资金数据是否完整。"
            )

    return {
        "is_seed": is_seed,
        "seed_score": seed_score,
        "seed_score_max": V23_SEED_SCORE_MAX,
        "reason": "；".join(reason_parts),
        "conditions": conditions_result,
        "audit_log": audit_log,
        "false_kill_warning": false_kill_warning,
    }


# ============================================================
# 四、交易权限判定
# ============================================================

def calc_trade_permission(
    rating: str,
    market_state: dict,
    seed_result: dict,
    market_score: float = 0.0
) -> dict:
    """
    计算交易权限（P0-P5）

    规则：
    1. 基础映射：评级S→P5, A→P4, B→P3, C→P2, D→P1, F→P0
    2. 市场环境修正：市场环境<10时最高C级（保持V2.1规则）
    3. 种子股修正：识别为新周期种子股时，允许提升一级
    4. S3退潮期：非种子股最高P1（禁止中高位接力）
    """
    permission_reasons = []

    # 1. 基础映射
    base_permission = V22_RATING_TO_PERMISSION.get(rating, "P0")
    permission_reasons.append(f"基础评级{rating}→{base_permission}")

    # 2. 市场环境上限修正（V2.1规则保持）
    final_rating = rating
    if market_score < V22_ENV_LOW_THRESHOLD:
        if _rating_higher(rating, V22_ENV_LOW_MAX_RATING):
            final_rating = V22_ENV_LOW_MAX_RATING
            permission_reasons.append(
                f"市场环境{market_score:.1f}分<{V22_ENV_LOW_THRESHOLD}，评级上限{V22_ENV_LOW_MAX_RATING}"
            )

    # 3. 种子股提升一级
    if seed_result.get("is_seed", False) and V22_SEED_RATING_BOOST:
        boosted = V22_SEED_BOOST_LEVELS.get(final_rating)
        if boosted:
            permission_reasons.append(f"新周期种子股，评级{final_rating}→{boosted}（提升一级）")
            final_rating = boosted
        else:
            permission_reasons.append(f"新周期种子股，但{final_rating}级已达上限不再提升")

    # 4. S3退潮期特殊限制：非种子股最高P1
    if market_state["state"] == "S3" and not seed_result.get("is_seed", False):
        s3_permission = "P1"
        if _permission_higher(base_permission, s3_permission):
            permission_reasons.append("S3退潮期，非种子股禁止中高位接力，权限上限P1")
            final_permission = s3_permission
        else:
            final_permission = V22_RATING_TO_PERMISSION.get(final_rating, base_permission)
    else:
        final_permission = V22_RATING_TO_PERMISSION.get(final_rating, base_permission)

    # 5. S4新周期试错期：种子股最低P2
    if market_state["state"] == "S4" and seed_result.get("is_seed", False):
        if _permission_higher("P2", final_permission):
            permission_reasons.append("S4新周期试错期，种子股允许试错，权限最低P2")
            final_permission = "P2"

    # 获取权限详情
    perm_info = V22_TRADE_PERMISSIONS.get(final_permission, V22_TRADE_PERMISSIONS["P0"])
    position = f"{perm_info['position_min']}%-{perm_info['position_max']}%"

    # 风险原因
    risk_reasons = []
    if market_state["state"] == "S3":
        risk_reasons.append("市场退潮期")
    if market_state["state"] == "S4":
        risk_reasons.append("新周期试错期，方向未确认")
    if not seed_result.get("is_seed", False) and market_state["state"] in ("S3", "S4"):
        risk_reasons.append("非种子股")

    return {
        "permission": final_permission,
        "permission_name": perm_info["name"],
        "permission_desc": perm_info["desc"],
        "recommended_position": position,
        "position_min": perm_info["position_min"],
        "position_max": perm_info["position_max"],
        "color": perm_info["color"],
        "permission_reason": permission_reasons,
        "risk_reasons": risk_reasons,
        "final_rating": final_rating
    }


def _rating_higher(r1: str, r2: str) -> bool:
    """判断评级r1是否高于r2"""
    order = {"S": 5, "A": 4, "B": 3, "C": 2, "D": 1, "F": 0}
    return order.get(r1, 0) > order.get(r2, 0)


def _permission_higher(p1: str, p2: str) -> bool:
    """判断权限p1是否高于p2"""
    order = {"P5": 5, "P4": 4, "P3": 3, "P2": 2, "P1": 1, "P0": 0}
    return order.get(p1, 0) > order.get(p2, 0)


# ============================================================
# 五、主入口：完整周期状态识别
# ============================================================

def detect_cycle_state(
    market_data: dict,
    stock: dict = None,
    rating: str = "C",
    market_score: float = 0.0
) -> dict:
    """
    V2.2 周期状态识别器主入口

    输入：
      market_data: 市场数据（最高板、各板数量、晋级率、炸板率等）
      stock: 个股数据（用于种子股识别，可为None）
      rating: V2.1评分评级（S/A/B/C/D/F）
      market_score: V2.1市场环境模块得分

    输出：
      {
        "cycle_state": "S4",
        "cycle_state_name": "新周期试错期",
        "cycle_switch_score": 5,
        "cycle_switch_level": "高概率切换期",
        "seed_stock": true/false,
        "seed_reason": "...",
        "trade_permission": "P2",
        "trade_permission_name": "试错",
        "recommended_position": "10%-20%",
        "permission_reason": [...],
        "risk_reasons": [...],
        "switch_conditions": [...],
        "seed_conditions": [...]
      }
    """
    # 1. 计算周期切换指数
    switch_result = calc_cycle_switch_score(market_data)

    # 补充 has_core_2board 到 market_data
    if "has_core_2board" not in market_data:
        market_data["has_core_2board"] = any(
            c["hit"] for c in switch_result["conditions"] if c["id"] == "cond6"
        )

    # 2. 识别市场状态
    market_state = detect_market_state(market_data, switch_result)

    # 3. 种子股识别（如果提供了个股数据）
    seed_result = {
        "is_seed": False,
        "seed_score": 0,
        "seed_score_max": V23_SEED_SCORE_MAX,
        "reason": "未提供个股数据",
        "conditions": [],
        "audit_log": {},
        "false_kill_warning": "",
    }
    if stock is not None:
        seed_result = detect_seed_stock(stock, market_data, switch_result)

    # 4. 交易权限判定
    permission_result = calc_trade_permission(
        rating=rating,
        market_state=market_state,
        seed_result=seed_result,
        market_score=market_score
    )

    return {
        "cycle_state": market_state["state"],
        "cycle_state_name": market_state["name"],
        "cycle_state_desc": market_state["desc"],
        "cycle_state_behavior": market_state["behavior"],
        "cycle_state_color": market_state["color"],
        "cycle_state_reason": market_state["reason"],
        "cycle_switch_score": switch_result["score"],
        "cycle_switch_level": switch_result["level"],
        "cycle_switch_color": switch_result["level_color"],
        "switch_conditions": switch_result["conditions"],
        "seed_stock": seed_result["is_seed"],
        "seed_score": seed_result.get("seed_score", 0),
        "seed_score_max": seed_result.get("seed_score_max", V23_SEED_SCORE_MAX),
        "seed_reason": seed_result["reason"],
        "seed_conditions": seed_result.get("conditions", []),
        "seed_audit_log": seed_result.get("audit_log", {}),
        "false_kill_warning": seed_result.get("false_kill_warning", ""),
        "trade_permission": permission_result["permission"],
        "trade_permission_name": permission_result["permission_name"],
        "trade_permission_desc": permission_result["permission_desc"],
        "recommended_position": permission_result["recommended_position"],
        "position_min": permission_result["position_min"],
        "position_max": permission_result["position_max"],
        "permission_color": permission_result["color"],
        "permission_reason": permission_result["permission_reason"],
        "risk_reasons": permission_result["risk_reasons"],
        "final_rating": permission_result["final_rating"]
    }
