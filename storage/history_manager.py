# -*- coding: utf-8 -*-

"""
============================================================
A股打板情绪仪表盘 V3.0.9

历史数据管理模块

功能：

1. 保存每日情绪数据
2. 读取历史五日数据
3. 自动兼容旧CSV
4. 自动补齐字段
5. 修复 emotion_score 读取为0问题

============================================================
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from config import (
    EMOTION_HISTORY_FILE,
    EMOTION_HISTORY_COLUMNS
)


# ============================================================
# 创建历史文件
# ============================================================

def _ensure_file():
    path = Path(
        EMOTION_HISTORY_FILE
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    if not path.exists():
        pd.DataFrame(
            columns=EMOTION_HISTORY_COLUMNS
        ).to_csv(
            path,
            index=False,
            encoding="utf-8-sig"
        )


# ============================================================
# 字段标准化
# ============================================================

def _normalize_columns(
        df: pd.DataFrame
) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=EMOTION_HISTORY_COLUMNS
        )

    rename_map = {}

    for col in df.columns:

        text = str(col).strip()

        if text.lower() == "score":

            rename_map[col] = "emotion_score"



        elif text == "情绪分":

            rename_map[col] = "emotion_score"



        elif text == "最高高度":

            rename_map[col] = "highest_board"

    if rename_map:
        df = df.rename(
            columns=rename_map
        )

    for col in EMOTION_HISTORY_COLUMNS:

        if col not in df.columns:
            df[col] = ""

    return df[
        EMOTION_HISTORY_COLUMNS
    ]


# ============================================================
# 读取历史
# ============================================================

def load_history() -> pd.DataFrame:
    _ensure_file()

    try:

        df = pd.read_csv(

            EMOTION_HISTORY_FILE,

            dtype={

                "date": str

            }

        )


    except Exception:

        return pd.DataFrame(
            columns=EMOTION_HISTORY_COLUMNS
        )

    df = _normalize_columns(
        df
    )

    if df.empty:
        return df

    df["date"] = (
        df["date"]
        .astype(str)
    )

    df = df.sort_values(
        by="date"
    )

    numeric_columns = [

        "emotion_score",

        "highest_board",

        "limit_up_count",

        "limit_down_count",

        "open_board_count",

        "open_board_rate",

        "rate_12",

        "rate_23",

        "break_rate"

    ]

    for col in numeric_columns:
        df[col] = pd.to_numeric(

            df[col],

            errors="coerce"

        ).fillna(0)

    return df.reset_index(
        drop=True
    )


# ============================================================
# 保存历史
# ============================================================

def save_history(
        record: dict
):
    """
    保存当天数据

    修复：

    emotion_score对象类型导致历史变0

    """

    _ensure_file()

    history = load_history()

    clean_record = {}

    for col in EMOTION_HISTORY_COLUMNS:

        value = record.get(

            col,

            ""

        )

        if col in [

            "emotion_score",

            "highest_board",

            "limit_up_count",

            "limit_down_count",

            "open_board_count",

            "open_board_rate",

            "rate_12",

            "rate_23",

            "break_rate"

        ]:

            try:

                value = float(value)



            except:

                # 尝试对象属性

                try:

                    value = float(
                        getattr(
                            value,
                            "score"
                        )
                    )


                except:

                    value = 0

        clean_record[col] = value

    new_row = pd.DataFrame(

        [

            clean_record

        ]

    )

    new_row = _normalize_columns(

        new_row

    )

    # 删除当天旧数据

    if not history.empty:
        history = history[

            history["date"].astype(str)

            !=

            str(record.get("date"))

            ]

    result = pd.concat(

        [

            history,

            new_row

        ],

        ignore_index=True

    )

    result = _normalize_columns(

        result

    )

    result = result.sort_values(

        by="date"

    )

    result.to_csv(

        EMOTION_HISTORY_FILE,

        index=False,

        encoding="utf-8-sig"

    )


# ============================================================
# 最近N日历史
# ============================================================

def get_recent_history(

        days: int = 5

) -> pd.DataFrame:
    df = load_history()

    if df.empty:
        return df

    return df.tail(

        days

    ).reset_index(

        drop=True

    )


# ============================================================
# 砸盘历史保存
# ============================================================

def save_smash_history(
        record: dict
):
    """
    保存当天砸盘情绪历史到 smash_history.csv

    record 字段：
        date, smash_score, highest_board, highest_stock,
        rate_23, rate_34, rate_45, rate_56
    """
    from config import SMASH_HISTORY_FILE, SMASH_HISTORY_COLUMNS

    # 确保目录存在
    SMASH_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)

    # 读取现有数据
    if SMASH_HISTORY_FILE.exists():
        try:
            df = pd.read_csv(SMASH_HISTORY_FILE, dtype={"date": str})
        except Exception:
            df = pd.DataFrame(columns=SMASH_HISTORY_COLUMNS)
    else:
        df = pd.DataFrame(columns=SMASH_HISTORY_COLUMNS)

    # 删除当天旧数据（去重）
    if not df.empty:
        df = df[df["date"].astype(str) != str(record.get("date"))]

    # 构建新行
    clean_record = {}
    for col in SMASH_HISTORY_COLUMNS:
        value = record.get(col, "")
        # 数值类型转换
        if col in ("smash_score", "highest_board", "rate_23", "rate_34", "rate_45", "rate_56"):
            try:
                value = float(value) if value != "" else 0.0
            except (ValueError, TypeError):
                value = 0.0
        clean_record[col] = value

    new_row = pd.DataFrame([clean_record])

    # 合并并排序
    result = pd.concat([df, new_row], ignore_index=True)
    result = result.sort_values(by="date").reset_index(drop=True)

    # 只保留定义的列
    for col in SMASH_HISTORY_COLUMNS:
        if col not in result.columns:
            result[col] = ""
    result = result[SMASH_HISTORY_COLUMNS]

    result.to_csv(SMASH_HISTORY_FILE, index=False, encoding="utf-8-sig")