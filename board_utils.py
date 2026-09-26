# -*- coding: utf-8 -*-

"""
============================================================
A股打板情绪仪表盘 V3.0.1

股票字段解析工具

功能：

1. 股票代码标准化
2. 股票名称识别
3. 连板数解析
4. 涨停池字段兼容
5. 数据统一格式化

============================================================
"""


from __future__ import annotations


import re

import pandas as pd



# ============================================================
# 字段搜索
# ============================================================

def find_column(
    df:pd.DataFrame,
    candidates:list[str]
)->str|None:

    """
    自动寻找DataFrame字段
    """

    if df is None or df.empty:
        return None


    # 精确匹配

    for name in candidates:

        if name in df.columns:
            return name



    # 模糊匹配

    for col in df.columns:

        text=str(col)

        for name in candidates:

            if name in text:
                return col


    return None



# ============================================================
# 股票代码标准化
# ============================================================

def normalize_code(
    value:object
)->str:

    """
    股票代码统一

    支持：

    sh600000
    SZ000001
    000001.SZ
    600000

    返回：

    六位数字代码

    """

    if pd.isna(value):
        return ""


    text=str(value).upper()


    digits=re.findall(
        r"\d+",
        text
    )


    if not digits:
        return ""


    code=digits[0]


    return code[-6:].zfill(6)



# ============================================================
# 连板数解析
# ============================================================

def parse_board(
    value:object
)->int:

    """
    解析连板数量

    支持：

    3
    3板
    三连板
    涨停统计: 5天4板

    """

    if pd.isna(value):
        return 0



    text=str(value)



    # 直接数字

    nums=re.findall(
        r"\d+",
        text
    )


    if nums:

        # 多数字情况：
        #
        # 例如：
        # 5天4板
        #
        # 取最后一个数字

        return int(nums[-1])



    # 中文数字

    mapping={
        "一":1,
        "二":2,
        "三":3,
        "四":4,
        "五":5,
        "六":6,
        "七":7,
        "八":8,
        "九":9,
    }


    for k,v in mapping.items():

        if k+"板" in text:

            return v



    return 0



# ============================================================
# 连板字段
# ============================================================

def get_board_column(
    df:pd.DataFrame
)->str|None:

    return find_column(
        df,
        [

            "连板数",

            "连续涨停天数",

            "连板",

            "涨停统计",

            "涨停次数",

            "涨停天数",

            "板数"

        ]
    )



# ============================================================
# 标准涨停池格式
# ============================================================

def board_frame(
    df:pd.DataFrame
)->pd.DataFrame:

    """
    输出统一格式：

    code
    name
    board

    """

    if df is None or df.empty:

        return pd.DataFrame(
            columns=[
                "code",
                "name",
                "board"
            ]
        )



    code_col=find_column(
        df,
        [
            "代码",
            "股票代码",
            "证券代码",
            "code",
            "symbol"
        ]
    )


    name_col=find_column(
        df,
        [
            "名称",
            "股票名称",
            "股票简称",
            "证券简称",
            "name"
        ]
    )


    board_col=get_board_column(df)



    if not code_col or not board_col:

        return pd.DataFrame(
            columns=[
                "code",
                "name",
                "board"
            ]
        )



    result=pd.DataFrame()



    result["code"]=(
        df[code_col]
        .map(normalize_code)
    )



    result["board"]=(
        df[board_col]
        .map(parse_board)
    )



    if name_col:

        result["name"]=(
            df[name_col]
            .astype(str)
        )

    else:

        result["name"]=result["code"]



    result=result[

        (result["code"]!="")

        &

        (result["board"]>0)

    ]



    # 一个股票只保留一次

    result=result.drop_duplicates(
        subset=[
            "code"
        ],
        keep="first"
    )


    return result.reset_index(
        drop=True
    )