# -*- coding: utf-8 -*-
"""
============================================================
A股打板情绪仪表盘 V3.2
龙头监控模块

功能：
1. 最高板/高标股封板状态监控
2. 连板梯队详细股票列表
3. 高位炸板股识别（昨日连板今日炸板）
4. 高位分歧风险信号

输入：涨停池 / 炸板池 / 昨日涨停池
输出：龙头监控结构化数据
============================================================
"""

import pandas as pd


def _col(df, keywords):
    """安全获取列名（模糊匹配）"""
    if df is None or df.empty:
        return None
    for kw in keywords:
        for col in df.columns:
            if kw in str(col):
                return col
    return None


def _fmt_time(val):
    """格式化封板时间 093001 -> 09:30"""
    try:
        s = str(int(float(val))).zfill(6)
        return f"{s[:2]}:{s[2:4]}"
    except Exception:
        return "--"


def _fmt_amount(val):
    """格式化封板资金 元 -> 万元/亿元"""
    try:
        v = float(val)
        if v >= 1e8:
            return f"{v / 1e8:.2f}亿"
        elif v >= 1e4:
            return f"{v / 1e4:.0f}万"
        else:
            return f"{v:.0f}"
    except Exception:
        return "--"


def _stock_status(open_count, in_limit=True):
    """判断封板状态"""
    try:
        oc = int(float(open_count))
    except Exception:
        oc = 0
    if not in_limit:
        return "已炸板"
    if oc > 0:
        return "回封"
    return "封板"


def _extract_stock(row, code_col, name_col, board_col, first_col, last_col,
                    seal_col, open_col, industry_col, turnover_col, in_limit=True):
    """从DataFrame行提取股票信息字典"""
    def gv(col):
        if col and col in row.index:
            value = row[col]
            return "" if value is None or pd.isna(value) else value
        return ""

    open_count = 0
    try:
        open_count = int(float(gv(open_col)))
    except Exception:
        pass

    return {
        "code": str(gv(code_col)).strip(),
        "name": str(gv(name_col)).strip(),
        "board": int(float(gv(board_col))) if gv(board_col) != "" else 0,
        "first_time": _fmt_time(gv(first_col)),
        "last_time": _fmt_time(gv(last_col)),
        "seal_amount": _fmt_amount(gv(seal_col)),
        "seal_raw": float(gv(seal_col)) if gv(seal_col) != "" else 0,
        "open_count": open_count,
        "industry": str(gv(industry_col)).strip() if gv(industry_col) != "" else "--",
        "turnover": f"{float(gv(turnover_col)):.2f}%" if gv(turnover_col) != "" else "--",
        "status": _stock_status(gv(open_col), in_limit),
    }


def build_leader_monitor(limit_up, open_board, previous_limit_up):
    """
    构建龙头监控数据

    参数：
        limit_up: 今日涨停池 DataFrame
        open_board: 今日炸板池 DataFrame
        previous_limit_up: 昨日涨停池 DataFrame

    返回：
        dict 龙头监控数据
    """
    # 列名映射
    code_col = _col(limit_up, ["代码", "code"])
    name_col = _col(limit_up, ["名称", "name"])
    board_col = _col(limit_up, ["连板数", "连续涨停", "board"])
    first_col = _col(limit_up, ["首次封板", "first_seal_time", "seal_time"])
    last_col = _col(limit_up, ["最后封板", "last_seal_time"])
    seal_col = _col(limit_up, ["封板资金", "封单", "seal_amount"])
    open_col = _col(limit_up, ["炸板次数", "open_count"])
    industry_col = _col(limit_up, ["所属行业", "行业", "industry"])
    turnover_col = _col(limit_up, ["换手率", "turnover"])

    # 炸板池列
    ob_code_col = _col(open_board, ["代码", "code"])
    ob_name_col = _col(open_board, ["名称", "name"])
    ob_open_col = _col(open_board, ["炸板次数"])
    ob_industry_col = _col(open_board, ["所属行业", "行业"])
    ob_first_col = _col(open_board, ["首次封板"])

    # 昨日涨停池列
    prev_code_col = _col(previous_limit_up, ["代码", "code"])
    prev_board_col = _col(previous_limit_up, ["连板数", "连续涨停", "board"])

    result = {
        "highest": {},
        "high_boards": [],
        "ladder_detail": {},
        "high_break": [],
        "signals": {
            "highest_break": False,
            "high_break_rate": 0.0,
            "ladder_gap": False,
            "gap_detail": "",
            "risk_level": "低",
            "risk_desc": "",
        }
    }

    if limit_up is None or limit_up.empty:
        result["signals"]["risk_desc"] = "今日无涨停数据"
        return result

    # ========== 1. 连板梯队详细列表 ==========
    ladder_detail = {}
    all_stocks = []

    for _, row in limit_up.iterrows():
        stock = _extract_stock(
            row, code_col, name_col, board_col, first_col, last_col,
            seal_col, open_col, industry_col, turnover_col, in_limit=True
        )
        if stock["board"] <= 0:
            stock["board"] = 1
        all_stocks.append(stock)
        b = stock["board"]
        if b not in ladder_detail:
            ladder_detail[b] = []
        ladder_detail[b].append(stock)

    # 按封板时间排序（早的在前）
    for b in ladder_detail:
        ladder_detail[b].sort(key=lambda x: x["first_time"])

    result["ladder_detail"] = {str(k): v for k, v in sorted(ladder_detail.items())}

    # ========== 2. 最高板 ==========
    max_board = max(s["board"] for s in all_stocks) if all_stocks else 0
    highest_stocks = [s for s in all_stocks if s["board"] == max_board]
    if highest_stocks:
        # 取封板时间最早的
        highest_stocks.sort(key=lambda x: x["first_time"])
        result["highest"] = highest_stocks[0]
        result["highest"]["co_leaders"] = [s["name"] for s in highest_stocks[1:]] if len(highest_stocks) > 1 else []

    # ========== 3. 高标股（3板及以上） ==========
    high_boards = [s for s in all_stocks if s["board"] >= 3]
    high_boards.sort(key=lambda x: (-x["board"], x["first_time"]))
    result["high_boards"] = high_boards

    # ========== 4. 高位炸板股（昨日连板>=2 今日炸板） ==========
    high_break = []
    if open_board is not None and not open_board.empty and previous_limit_up is not None and not previous_limit_up.empty:
        # 昨日连板>=2的股票代码集合
        prev_high_codes = {}
        for _, row in previous_limit_up.iterrows():
            try:
                code = str(row[prev_code_col]).strip()
                board = int(float(row[prev_board_col]))
                if board >= 2:
                    prev_high_codes[code] = board
            except Exception:
                continue

        # 今日炸板池中匹配
        for _, row in open_board.iterrows():
            try:
                code = str(row[ob_code_col]).strip()
                if code in prev_high_codes:
                    open_count = 0
                    try:
                        open_count = int(float(row[ob_open_col]))
                    except Exception:
                        pass
                    high_break.append({
                        "code": code,
                        "name": str(row[ob_name_col]).strip(),
                        "yesterday_board": prev_high_codes[code],
                        "open_count": open_count,
                        "industry": str(row[ob_industry_col]).strip() if ob_industry_col and ob_industry_col in row.index else "--",
                        "first_time": _fmt_time(row[ob_first_col]) if ob_first_col and ob_first_col in row.index else "--",
                    })
            except Exception:
                continue

    result["high_break"] = high_break

    # ========== 5. 风险信号 ==========
    signals = result["signals"]

    # 5.1 最高板是否炸板
    if result["highest"]:
        signals["highest_break"] = result["highest"]["open_count"] > 0 or result["highest"]["status"] == "已炸板"

    # 5.2 高位炸板率（昨日高标股中今日炸板的比例）
    if previous_limit_up is not None and not previous_limit_up.empty and prev_board_col:
        try:
            prev_high_count = len(previous_limit_up[previous_limit_up[prev_board_col].astype(float) >= 2])
            if prev_high_count > 0:
                signals["high_break_rate"] = round(len(high_break) / prev_high_count * 100, 1)
        except Exception:
            pass

    # 5.3 连板梯队断层检测
    boards_present = sorted(ladder_detail.keys())
    if len(boards_present) >= 2:
        gaps = []
        for i in range(len(boards_present) - 1):
            if boards_present[i + 1] - boards_present[i] > 1:
                gaps.append(f"{boards_present[i]}板→{boards_present[i + 1]}板")
        if gaps:
            signals["ladder_gap"] = True
            signals["gap_detail"] = "、".join(gaps) + " 断层"

    # 5.4 综合风险等级
    risk_score = 0
    risk_factors = []

    if signals["highest_break"]:
        risk_score += 3
        risk_factors.append("最高板炸板")

    if signals["high_break_rate"] >= 50:
        risk_score += 3
        risk_factors.append(f"高位炸板率{signals['high_break_rate']}%")
    elif signals["high_break_rate"] >= 30:
        risk_score += 2
        risk_factors.append(f"高位炸板率{signals['high_break_rate']}%")

    if signals["ladder_gap"]:
        risk_score += 1
        risk_factors.append(signals["gap_detail"])

    # 高标股数量
    if len(high_boards) == 0 and max_board >= 3:
        risk_score += 1
        risk_factors.append("3板及以上高标股缺失")

    if risk_score >= 5:
        signals["risk_level"] = "高"
    elif risk_score >= 3:
        signals["risk_level"] = "中"
    else:
        signals["risk_level"] = "低"

    if risk_factors:
        signals["risk_desc"] = "风险信号：" + "；".join(risk_factors)
    else:
        signals["risk_desc"] = "最高板封板稳固，高标股健康，连板梯队完整"

    return result
