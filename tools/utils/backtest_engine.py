# -*- coding: utf-8 -*-
"""
============================================================
A股打板情绪仪表盘 V3.2
历史回测引擎

读取 emotion_history.csv + smash_history.csv，计算：
  - 概览统计（交易日数、平均情绪分、极值等）
  - 情绪分区间回测（各区间次日赚钱效应）
  - 砸盘情绪回测
  - 最高板回测
  - 连板晋级率统计
  - 历史走势数据
============================================================
"""

import pandas as pd
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


def _load_emotion_history() -> pd.DataFrame:
    """加载情绪历史数据"""
    path = DATA_DIR / "emotion_history.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, dtype={"date": str})
    df = df.sort_values("date").reset_index(drop=True)
    return df


def _load_smash_history() -> pd.DataFrame:
    """加载砸盘历史数据"""
    path = DATA_DIR / "smash_history.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, dtype={"date": str})
    df = df.sort_values("date").reset_index(drop=True)
    return df


def _safe_float(v, default=0.0):
    """安全转float，处理NaN"""
    try:
        if pd.isna(v):
            return default
        return float(v)
    except Exception:
        return default


def calc_overview(df: pd.DataFrame) -> dict:
    """概览统计"""
    if df.empty:
        return {}

    n = len(df)
    return {
        "total_days": n,
        "date_range": f"{df['date'].iloc[0]} ~ {df['date'].iloc[-1]}",
        "avg_emotion": round(_safe_float(df["emotion_score"].mean()), 2),
        "max_emotion": round(_safe_float(df["emotion_score"].max()), 2),
        "max_emotion_date": str(df.loc[df["emotion_score"].idxmax(), "date"]),
        "min_emotion": round(_safe_float(df["emotion_score"].min()), 2),
        "min_emotion_date": str(df.loc[df["emotion_score"].idxmin(), "date"]),
        "avg_limit_up": round(_safe_float(df["limit_up_count"].mean()), 1),
        "avg_open_board_rate": round(_safe_float(df["open_board_rate"].mean()), 2),
        "avg_highest_board": round(_safe_float(df["highest_board"].mean()), 1),
        "avg_rate_12": round(_safe_float(df["rate_12"].mean()), 2),
        "avg_rate_23": round(_safe_float(df["rate_23"].mean()), 2),
    }


def calc_emotion_zones(df: pd.DataFrame) -> list:
    """
    情绪分区间回测（核心）
    按当日情绪分分区间，统计次日情绪分变化、次日涨停数变化
    用次日变化作为赚钱效应代理指标
    """
    if df.empty or len(df) < 2:
        return []

    # 计算次日变化
    df = df.copy()
    df["next_emotion"] = df["emotion_score"].shift(-1)
    df["next_emotion_change"] = df["next_emotion"] - df["emotion_score"]
    df["next_limit_up"] = df["limit_up_count"].shift(-1)
    df["next_limit_up_change"] = df["next_limit_up"] - df["limit_up_count"]
    df["next_highest_board"] = df["highest_board"].shift(-1)

    # 去掉最后一行（无次日数据）
    df_valid = df.iloc[:-1].copy()

    zones = [
        {"name": "冰点 (<30)", "min": 0, "max": 30, "color": "#2ebd85"},
        {"name": "低迷 (30-50)", "min": 30, "max": 50, "color": "#7dd3a8"},
        {"name": "中性 (50-70)", "min": 50, "max": 70, "color": "#f0b90b"},
        {"name": "活跃 (70-85)", "min": 70, "max": 85, "color": "#ff8a3c"},
        {"name": "高潮 (>85)", "min": 85, "max": 200, "color": "#f6465d"},
    ]

    result = []
    for z in zones:
        mask = (df_valid["emotion_score"] >= z["min"]) & (df_valid["emotion_score"] < z["max"])
        sub = df_valid[mask]
        count = len(sub)
        if count == 0:
            result.append({
                "zone": z["name"],
                "color": z["color"],
                "count": 0,
                "ratio": 0,
                "avg_next_emotion_change": 0,
                "avg_next_limit_up_change": 0,
                "up_probability": 0,
                "sample_enough": False,
            })
            continue

        # 次日情绪分上升概率（赚钱效应代理）
        up_count = (sub["next_emotion_change"] > 0).sum()
        up_prob = round(up_count / count * 100, 1)

        result.append({
            "zone": z["name"],
            "color": z["color"],
            "count": count,
            "ratio": round(count / len(df_valid) * 100, 1),
            "avg_next_emotion_change": round(_safe_float(sub["next_emotion_change"].mean()), 2),
            "avg_next_limit_up_change": round(_safe_float(sub["next_limit_up_change"].mean()), 1),
            "up_probability": up_prob,
            "sample_enough": count >= 5,
        })

    return result


def calc_smash_backtest(df_smash: pd.DataFrame, df_emotion: pd.DataFrame) -> dict:
    """砸盘情绪回测"""
    if df_smash.empty or df_emotion.empty:
        return {"zones": [], "correlation": 0}

    # 合并砸盘数据和次日情绪变化
    df = df_smash.merge(
        df_emotion[["date", "emotion_score"]],
        on="date", how="left"
    )
    df = df.sort_values("date").reset_index(drop=True)
    df["next_emotion"] = df["emotion_score"].shift(-1)
    df["next_emotion_change"] = df["next_emotion"] - df["emotion_score"]
    df_valid = df.iloc[:-1].copy()

    if df_valid.empty:
        return {"zones": [], "correlation": 0, "total": 0}

    # 砸盘分数区间
    zones = [
        {"name": "极低 (<2)", "min": 0, "max": 2},
        {"name": "低 (2-4)", "min": 2, "max": 4},
        {"name": "中性 (4-6)", "min": 4, "max": 6},
        {"name": "高 (6-8)", "min": 6, "max": 8},
        {"name": "极高 (>8)", "min": 8, "max": 100},
    ]

    zone_results = []
    for z in zones:
        mask = (df_valid["smash_score"] >= z["min"]) & (df_valid["smash_score"] < z["max"])
        sub = df_valid[mask]
        count = len(sub)
        if count == 0:
            zone_results.append({"zone": z["name"], "count": 0, "avg_next_change": 0, "up_prob": 0})
            continue
        up_count = (sub["next_emotion_change"] > 0).sum()
        zone_results.append({
            "zone": z["name"],
            "count": count,
            "avg_next_change": round(_safe_float(sub["next_emotion_change"].mean()), 2),
            "up_prob": round(up_count / count * 100, 1),
        })

    # 砸盘分数与次日情绪变化的相关性
    try:
        corr = round(_safe_float(df_valid["smash_score"].corr(df_valid["next_emotion_change"])), 3)
    except Exception:
        corr = 0

    return {
        "zones": zone_results,
        "correlation": corr,
        "total": len(df_valid),
        "interpretation": _interpret_smash_corr(corr),
    }


def _interpret_smash_corr(corr: float) -> str:
    """解读砸盘分数与次日情绪变化的相关性"""
    if corr > 0.3:
        return "砸盘分数越高，次日情绪越容易上升（砸盘后反弹效应）"
    elif corr < -0.3:
        return "砸盘分数越高，次日情绪越容易继续下跌（砸盘惯性）"
    else:
        return "砸盘分数与次日情绪变化相关性较弱，需更多样本验证"


def calc_highest_board_backtest(df: pd.DataFrame) -> list:
    """最高板回测：不同最高板高度下的次日晋级率和情绪变化"""
    if df.empty or len(df) < 2:
        return []

    df = df.copy()
    df["next_rate_12"] = df["rate_12"].shift(-1)
    df["next_emotion_change"] = df["emotion_score"].shift(-1) - df["emotion_score"]
    df_valid = df.iloc[:-1].copy()

    levels = [
        {"name": "3板及以下", "min": 0, "max": 4},
        {"name": "4板", "min": 4, "max": 5},
        {"name": "5板", "min": 5, "max": 6},
        {"name": "6板及以上", "min": 6, "max": 20},
    ]

    result = []
    for lv in levels:
        mask = (df_valid["highest_board"] >= lv["min"]) & (df_valid["highest_board"] < lv["max"])
        sub = df_valid[mask]
        count = len(sub)
        if count == 0:
            result.append({"level": lv["name"], "count": 0, "avg_next_rate_12": 0, "avg_next_emotion_change": 0})
            continue
        result.append({
            "level": lv["name"],
            "count": count,
            "avg_next_rate_12": round(_safe_float(sub["next_rate_12"].mean()), 2),
            "avg_next_emotion_change": round(_safe_float(sub["next_emotion_change"].mean()), 2),
        })

    return result


def calc_trend_data(df_emotion: pd.DataFrame, df_smash: pd.DataFrame) -> dict:
    """历史走势数据（供图表使用）"""
    dates = df_emotion["date"].tolist() if not df_emotion.empty else []
    emotion_scores = [round(_safe_float(v), 2) for v in df_emotion["emotion_score"].tolist()] if not df_emotion.empty else []
    highest_boards = [int(_safe_float(v, 0)) for v in df_emotion["highest_board"].tolist()] if not df_emotion.empty else []
    limit_ups = [round(_safe_float(v), 1) for v in df_emotion["limit_up_count"].tolist()] if not df_emotion.empty else []
    open_board_rates = [round(_safe_float(v), 2) for v in df_emotion["open_board_rate"].tolist()] if not df_emotion.empty else []

    smash_dates = df_smash["date"].tolist() if not df_smash.empty else []
    smash_scores = [round(_safe_float(v), 2) for v in df_smash["smash_score"].tolist()] if not df_smash.empty else []

    return {
        "dates": dates,
        "emotion_scores": emotion_scores,
        "highest_boards": highest_boards,
        "limit_ups": limit_ups,
        "open_board_rates": open_board_rates,
        "smash_dates": smash_dates,
        "smash_scores": smash_scores,
    }


def build_backtest() -> dict:
    """构建完整回测数据"""
    df_emotion = _load_emotion_history()
    df_smash = _load_smash_history()

    return {
        "overview": calc_overview(df_emotion),
        "emotion_zones": calc_emotion_zones(df_emotion),
        "smash_backtest": calc_smash_backtest(df_smash, df_emotion),
        "highest_board_backtest": calc_highest_board_backtest(df_emotion),
        "trend": calc_trend_data(df_emotion, df_smash),
        "sample_warning": len(df_emotion) < 20,
    }


if __name__ == "__main__":
    import json
    result = build_backtest()
    print(json.dumps(result, ensure_ascii=False, indent=2))
