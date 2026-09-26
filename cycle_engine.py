# -*- coding: utf-8 -*-

"""
============================================================
A股打板情绪仪表盘 V3.0.11

五日情绪周期分析模块

修复：
1. pandas Series读取异常
2. emotion_score历史读取为0
3. 兼容多种历史格式

============================================================
"""


from dataclasses import dataclass

import pandas as pd



@dataclass
class CycleResult:

    emotion_cycle:str

    height_cycle:str

    comprehensive:str

    trend:str

    description:str

    history:list

    stage:str



# ============================================================
# 安全转换
# ============================================================

def _safe_float(v,default=0):

    try:

        return float(v)

    except:

        return default



def _safe_int(v,default=0):

    try:

        return int(float(v))

    except:

        return default



# ============================================================
# 历史格式统一
# ============================================================

def _convert_history(history):


    if history is None:

        return []



    if isinstance(history,pd.DataFrame):

        return history.to_dict(
            "records"
        )



    if isinstance(history,list):

        return history



    if isinstance(history,dict):

        return [history]



    return []



# ============================================================
# 字段读取
# ============================================================

def _get(row,key,default=0):


    aliases={


        "emotion_score":[

            "emotion_score",

            "score",

            "emotionScore",

            "emotion"

        ],



        "highest_board":[

            "highest_board",

            "height",

            "board",

            "max_board"

        ]

    }



    keys=aliases.get(

        key,

        [key]

    )



    # dict

    if isinstance(row,dict):


        for k in keys:


            if k in row:

                return row[k]


        return default



    # pandas Series

    if isinstance(row,pd.Series):


        for k in keys:


            if k in row.index:

                return row[k]


        return default



    # 普通对象

    for k in keys:


        if hasattr(row,k):

            return getattr(
                row,
                k
            )



    return default



# ============================================================
# 情绪周期
# ============================================================

def judge_emotion(score):


    score=_safe_float(score)



    if score>=80:

        return "高潮期"



    if score>=65:

        return "活跃期"



    if score>=50:

        return "主升期"



    if score>=35:

        return "退潮期"



    return "冰点期"




# ============================================================
# 空间周期
# ============================================================

def judge_height(history):


    if not history:

        return "空间观察"



    boards=[

        _safe_int(

            _get(

                x,

                "highest_board",

                0

            )

        )

        for x in history

    ]



    latest=boards[-1]



    if latest>=8:

        return "空间扩张"



    if latest>=5:


        if len(boards)>=2 and latest>=boards[-2]:

            return "空间稳定"



        return "空间维持"



    if latest>=3:

        return "空间震荡"



    return "空间压缩"




# ============================================================
# 高度趋势
# ============================================================

def height_trend(history):


    if len(history)<2:

        return "→ 高度观察"



    boards=[


        _safe_int(

            _get(

                x,

                "highest_board",

                0

            )

        )

        for x in history


    ]



    if boards[-1]>boards[-2]:

        return "↑ 高度扩张"



    if boards[-1]==boards[-2]:

        return "→ 高度横盘"



    return "↓ 高度下降"




# ============================================================
# 综合阶段判断
# ============================================================

def judge_stage(

        emotion_cycle,

        height_cycle,

        history

):


    boards=[


        _safe_int(

            _get(

                x,

                "highest_board",

                0

            )

        )

        for x in history


    ]



    latest=boards[-1]



    previous=boards[-2]



    # 高度快速下降

    if (

        latest < previous

        and latest<=3

    ):

        return "退潮阶段"



    # 高位保持

    if (

        latest>=5

        and latest>=previous

    ):


        if emotion_cycle=="主升期":

            return "启动阶段"



    if emotion_cycle=="高潮期":

        return "高潮阶段"



    if emotion_cycle=="退潮期":

        return "退潮阶段"



    if emotion_cycle=="冰点期":

        return "冰点阶段"



    return "主升阶段"




# ============================================================
# 描述
# ============================================================

def build_description(stage):


    text={


        "退潮阶段":

        "高位亏钱效应明显，空间压缩，降低接力仓位。",



        "启动阶段":

        "高位亏钱效应仍在，但空间保持，市场处于退潮后的启动阶段，控制仓位等待核心方向确认。",



        "高潮阶段":

        "赚钱效应集中，注意高潮后的分歧风险。",



        "冰点阶段":

        "市场情绪极弱，等待冰点后的修复机会。",



        "主升阶段":

        "市场处于主升阶段，等待方向确认。"

    }



    return text.get(

        stage,

        "市场处于主升阶段，等待方向确认。"

    )




# ============================================================
# 主入口
# ============================================================

def analyze_cycle_legacy_frozen(

        history,

        smash=None,

        emotion=None

):


    history=_convert_history(history)



    if len(history)<5:


        return CycleResult(


            emotion_cycle="历史不足5个交易日",


            height_cycle="历史不足5个交易日",


            comprehensive="主升阶段",


            trend="→ 高度观察",


            description="历史数据不足，暂不判断周期。",


            history=history,


            stage="主升阶段"

        )



    latest=history[-1]



    emotion_cycle=judge_emotion(

        _get(

            latest,

            "emotion_score",

            0

        )

    )



    height_cycle=judge_height(

        history

    )



    stage=judge_stage(

        emotion_cycle,

        height_cycle,

        history

    )



    return CycleResult(


        emotion_cycle=emotion_cycle,


        height_cycle=height_cycle,


        comprehensive=stage,


        trend=height_trend(

            history

        ),


        description=build_description(

            stage

        ),


        history=history,


        stage=stage

    )

def analyze_cycle(history, smash=None, emotion=None):
    # 用户指定的资金周期仓位规则
    fund_cycle = 0
    if history and len(history) > 0:
        last = history[-1]
        fund_cycle = getattr(last, 'fund_cycle', 0) or 0
    # 阈值判断
    if fund_cycle <= -2:
        position = 90
        stage = "深度反击"
    elif fund_cycle <= 2:
        position = 80
        stage = "启动进攻"
    elif fund_cycle <= 5:
        position = 70
        stage = "均衡参与"
    elif fund_cycle <= 8:
        position = 50
        stage = "动能减弱"
    elif fund_cycle <= 13:
        position = 30
        stage = "防御减仓"
    elif fund_cycle <= 17:
        position = 10
        stage = "退潮警戒"
    else:
        position = 1
        stage = "脉冲尾声"
    result=CycleResult(emotion_cycle=None,height_cycle=None,comprehensive=None,
        trend=stage,description=f"五日资金周期{fund_cycle:.2f}%，对应{stage}，建议仓位{position}%",
        history=_convert_history(history),stage=stage)
    result.status="ACTIVE"
    result.position = position
    return result
