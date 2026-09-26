# -*- coding: utf-8 -*-

"""
============================================================
A股打板情绪仪表盘 V3.0.6

历史数据结构兼容层

功能：
1. 兼容旧CSV
2. 自动补字段
3. 修复emotion_score读取异常
4. 保留最高板历史
============================================================
"""

import pandas as pd


EMOTION_COLUMNS = [

    "date",

    "emotion_score",

    "limit_up_count",

    "limit_down_count",

    "open_board_count",

    "open_board_rate",

    "highest_board",

    "rate_12",

    "rate_23",

    "break_rate",

    "cycle_stage",

    "height_stage"
]


def normalize_history(df):

    """
    历史数据标准化
    """

    if df is None or df.empty:

        return pd.DataFrame(
            columns=EMOTION_COLUMNS
        )


    data=df.copy()


    # =========================
    # 字段兼容
    # =========================


    rename={}


    mapping={

        "score":
        "emotion_score",

        "emotion":
        "emotion_score",

        "情绪分":
        "emotion_score",

        "最高连板":
        "highest_board",

        "最高板":
        "highest_board",

        "涨停数":
        "limit_up_count",

        "涨停数量":
        "limit_up_count",

        "跌停数":
        "limit_down_count",

        "跌停数量":
        "limit_down_count",

    }


    for old,new in mapping.items():

        if old in data.columns and new not in data.columns:

            rename[old]=new


    if rename:

        data=data.rename(
            columns=rename
        )


    # =========================
    # 缺失字段补齐
    # =========================

    for col in EMOTION_COLUMNS:

        if col not in data.columns:

            if col in (
                "cycle_stage",
                "height_stage"
            ):

                data[col]=""

            else:

                data[col]=0



    # =========================
    # 类型修正
    # =========================

    numeric_cols=[

        "emotion_score",

        "limit_up_count",

        "limit_down_count",

        "open_board_count",

        "open_board_rate",

        "highest_board",

        "rate_12",

        "rate_23",

        "break_rate"

    ]


    for col in numeric_cols:

        data[col]=pd.to_numeric(

            data[col],

            errors="coerce"

        ).fillna(0)



    data["date"]=(
        data["date"]
        .astype(str)
        .str.replace(
            ".0",
            "",
            regex=False
        )
    )


    # =========================
    # 排序
    # =========================

    data=data.sort_values(
        "date"
    )


    return data[
        EMOTION_COLUMNS
    ].reset_index(
        drop=True
    )



def latest_history(df,days=5):

    """
    获取最近N日历史
    """

    data=normalize_history(df)


    if len(data)<=days:

        return data


    return data.tail(days)