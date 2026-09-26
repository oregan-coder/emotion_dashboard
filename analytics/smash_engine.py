# -*- coding: utf-8 -*-

"""
============================================================
A股打板情绪仪表盘 V3.0.16

砸盘情绪引擎

修复：
1. 保留V3.0.3接口
2. 修复最高板股票名称丢失
3. 修复砸盘分数计算
4. 增加历史记录字段支持

============================================================
"""


from dataclasses import dataclass

import pandas as pd



# ============================================================
# 数据结构
# ============================================================


@dataclass
class SmashResult:


    # 砸盘结果

    score: float

    state: str



    # 空间高度

    highest_board: int

    highest_stock: str



    # 晋级率

    rate12: float

    rate23: float

    rate34: float

    rate45: float

    rate56: float



    # 炸板率

    break_rate: float

    # 连板梯队

    first_board: int

    second_board: int

    third_board: int

    fourth_board: int

    fifth_board: int



    # 高位反馈

    high_count: int

    high_continue_count: int

    high_break_count: int

    high_loss_count: int

    high_feedback: str


    # 详细数据

    rates: dict

    smash_detail: dict

    @property
    def status(self):
        return self.state



# ============================================================
# 字段寻找
# ============================================================


def _find_col(
        df,
        names
):

    for c in names:

        if c in df.columns:

            return c

    for c in df.columns:

        if any(
            name in str(c)
            for name in names
        ):

            return c


    return None


def _parse_number(value, default=0):

    if pd.isna(value):

        return default

    text = str(
        value
    ).replace(
        "%",
        ""
    )

    match = pd.Series(
        [text]
    ).str.extract(
        r"(-?\d+(?:\.\d+)?)"
    )[0].iloc[0]

    if pd.isna(match):

        return default

    return float(
        match
    )



# ============================================================
# 数据标准化
# ============================================================


def _normalize(df):


    if df is None or df.empty:

        return pd.DataFrame(
            columns=[
                "code",
                "name",
                "board",
                "pct"
            ]
        )



    data=df.copy()



    code_col=_find_col(
        data,
        [
            "代码",
            "股票代码",
            "证券代码",
            "code"
        ]
    )



    name_col=_find_col(
        data,
        [
            "名称",
            "股票名称",
            "证券简称",
            "name"
        ]
    )



    board_col=_find_col(
        data,
        [
            "连板数",
            "连续涨停天数",
            "涨停次数",
            "板数",
            "board"
        ]
    )



    pct_col=_find_col(
        data,
        [
            "涨跌幅",
            "涨幅",
            "最新涨幅",
            "pct"
        ]
    )



    # 股票代码

    if code_col:


        data["code"]=(
            data[code_col]
            .astype(str)
            .str.extract(
                r"(\d{6})"
            )[0]
            .fillna("")
        )


    else:

        data["code"]=""



    # 股票名称

    if name_col:

        data["name"]=(
            data[name_col]
            .astype(str)
        )


    else:

        data["name"]=""



    # 连板高度

    if board_col:

        data["board"]=data[board_col].map(
            lambda x: int(
                _parse_number(
                    x,
                    1
                )
            )
        )


    else:

        data["board"]=1



    # 涨跌幅

    if pct_col:

        data["pct"]=data[pct_col].map(
            lambda x: _parse_number(
                x,
                0
            )
        )


    else:

        data["pct"]=0



    return data.reset_index(
        drop=True
    )
# ============================================================
# 晋级率计算
# ============================================================

def _promotion(previous, today, board):

    if previous.empty:
        return {
            "success": 0,
            "total": 0,
            "rate": 0
        }


    pool = previous[
        previous["board"] == board
    ]


    total = len(pool)


    if total == 0:
        return {
            "success": 0,
            "total": 0,
            "rate": 0
        }


    today_boards = dict(
        zip(
            today["code"],
            today["board"]
        )
    )


    success = sum(
        today_boards.get(
            code,
            0
        ) >= board + 1
        for code in pool["code"]
    )


    rate = round(
        success / total * 100,
        2
    )


    return {
        "success": success,
        "total": total,
        "rate": rate
    }


def _board_count(today, board):

    return int(
        (
            today["board"] == board
        )
        .sum()
    )


def _board_counts(today):

    return {
        "first_board": _board_count(
            today,
            1
        ),
        "second_board": _board_count(
            today,
            2
        ),
        "third_board": _board_count(
            today,
            3
        ),
        "fourth_board": _board_count(
            today,
            4
        ),
        "fifth_board": _board_count(
            today,
            5
        )
    }



# ============================================================
# 砸盘情绪核心公式
# ============================================================

def _smash_score(rates):

    """
    固定公式：

    统计：
    2进3
    3进4
    4进5
    5进6

    晋级率转小数

    相加 ÷4 ×10

    1进2不参与评分

    """


    values = [

        rates.get(
            "2_3",
            {}
        ).get(
            "rate",
            0
        ),

        rates.get(
            "3_4",
            {}
        ).get(
            "rate",
            0
        ),

        rates.get(
            "4_5",
            {}
        ).get(
            "rate",
            0
        ),

        rates.get(
            "5_6",
            {}
        ).get(
            "rate",
            0
        )

    ]


    score = sum(
        [
            x / 100
            for x in values
        ]
    )


    score = (
        score
        /
        4
        *
        10
    )


    return round(
        score,
        2
    )



# ============================================================
# 炸板率
# ============================================================

def _calc_break_rate(high):

    if high["high_count"] == 0:

        return 0


    return round(

        high["break"]
        /
        high["high_count"]
        *
        100,

        2
    )


def _high_feedback(previous, today, open_board=None):

    high_pool = previous[
        previous["board"] >= 4
    ]

    high_count = len(
        high_pool
    )

    if high_count == 0:

        return {
            "high_count": 0,
            "continue": 0,
            "break": 0,
            "loss": 0
        }

    today_boards = dict(
        zip(
            today["code"],
            today["board"]
        )
    )

    high_codes = set(
        high_pool["code"]
    )

    continue_count = sum(
        today_boards.get(
            row.code,
            0
        ) >= row.board + 1
        for row in high_pool.itertuples()
    )

    break_count = max(
        high_count - continue_count,
        0
    )

    loss_count = break_count

    return {
        "high_count": high_count,
        "continue": continue_count,
        "break": break_count,
        "loss": loss_count
    }

def _judge_high_feedback(high):

    if high.get("high_count",0)==0:
        return "暂无"


    high_count = high.get(
        "high_count",
        0
    )

    break_count = high.get(
        "break",
        0
    )


    if high_count == 0:
        return "暂无"


    break_rate = (
        break_count
        /
        high_count
        *
        100
    )


    if break_rate >= 70:
        return "高位晋级承压"


    if break_rate >= 50:
        return "高位出现分歧"


    return "高位正常"

def _highest(today):

    if today.empty:

        return 0, "暂无"

    highest_board = int(
        today["board"].max()
    )

    stocks = (
        today[
            today["board"] == highest_board
        ]["name"]
        .astype(str)
        .replace("", pd.NA)
        .dropna()
        .drop_duplicates()
        .tolist()
    )

    highest_stock = "|".join(
        stocks
    ) if stocks else "暂无"

    return highest_board, highest_stock


def _calc_smash_score(rates):
    """
    砸盘情绪核心公式

    只统计：
    2进3
    3进4
    4进5
    5进6

    1进2不参与评分

    公式：

    (二进三+三进四+四进五+五进六)/4*10
    """

    values = [

        rates.get(
            "2_3",
            {}
        ).get(
            "rate",
            0
        ),

        rates.get(
            "3_4",
            {}
        ).get(
            "rate",
            0
        ),

        rates.get(
            "4_5",
            {}
        ).get(
            "rate",
            0
        ),

        rates.get(
            "5_6",
            {}
        ).get(
            "rate",
            0
        )

    ]


    total = sum(
        [
            v / 100
            for v in values
        ]
    )


    score = (
        total
        /
        4
        *
        10
    )


    return round(
        score,
        2
    )



def _smash_state(score):
    """
    砸盘情绪状态映射（V3.2 周期分级）

    砸盘分 = 四档晋级率(2进3/3进4/4进5/5进6)平均 × 10

    分级：
      <3分    试错期
      3-5分   修复期
      5-7分   火热期
      7-9分   高潮期
      9-10分  砸盘期
      >10分   退潮期

    取消最高10分限制：分数本身不再封顶。
    """

    if score < 3:

        return "试错期"


    if score < 5:

        return "修复期"



    if score < 7:

        return "火热期"



    if score < 9:

        return "高潮期"



    if score <= 10:

        return "砸盘期"



    return "退潮期"



def calculate_smash(
        limit_up,
        previous_limit_up,
        open_board=None
):

    today = _normalize(
        limit_up
    )


    previous = _normalize(
        previous_limit_up
    )


    # 晋级率

    rates = {


        "1_2":
        _promotion(
            previous,
            today,
            1
        ),


        "2_3":
        _promotion(
            previous,
            today,
            2
        ),


        "3_4":
        _promotion(
            previous,
            today,
            3
        ),


        "4_5":
        _promotion(
            previous,
            today,
            4
        ),


        "5_6":
        _promotion(
            previous,
            today,
            5
        )

    }


    rate12 = rates["1_2"]["rate"]

    rate23 = rates["2_3"]["rate"]

    rate34 = rates["3_4"]["rate"]

    rate45 = rates["4_5"]["rate"]

    rate56 = rates["5_6"]["rate"]


    board_counts = _board_counts(
        today
    )



    # 高位反馈

    high = _high_feedback(
        previous,
        today,
        _normalize(open_board)
    )

    high_feedback = _judge_high_feedback(
        high
    )

    break_rate = _calc_break_rate(
        high
    )


    # 最高板

    highest_board, highest_stock = _highest(
        today
    )


    # 砸盘分数

    score = _calc_smash_score(
        rates
    )


    detail = {

        "rate12":rate12,

        "rate23":rate23,

        "rate34":rate34,

        "rate45":rate45,

        "rate56":rate56,

        "score_formula":
        "(2进3+3进4+4进5+5进6)/4*10"

    }


    return SmashResult(

        score=score,

        state=_smash_state(
            score
        ),


        highest_board=
        highest_board,


        highest_stock=
        highest_stock,


        rate12=rate12,

        rate23=rate23,

        rate34=rate34,

        rate45=rate45,

        rate56=rate56,


        break_rate=
        break_rate,

        first_board=
        board_counts["first_board"],

        second_board=
        board_counts["second_board"],

        third_board=
        board_counts["third_board"],

        fourth_board=
        board_counts["fourth_board"],

        fifth_board=
        board_counts["fifth_board"],


        high_count=
        high.get(
            "high_count",
            0
        ),


        high_continue_count=
        high.get(
            "continue",
            0
        ),


        high_break_count=
        high.get(
            "break",
            0
        ),

        high_feedback=high_feedback,


        high_loss_count=
        high.get(
            "loss",
            0
        ),


        rates=rates,


        smash_detail=detail

    )
