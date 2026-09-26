# -*- coding: utf-8 -*-

"""
============================================================
A股打板情绪仪表盘 V3.0.5

仓位管理引擎

============================================================
"""


def _get(obj,key,default=""):

    if obj is None:
        return default

    if isinstance(obj,dict):
        return obj.get(key,default)

    return getattr(
        obj,
        key,
        default
    )



def _float(v):

    try:
        return float(v)

    except:

        return 0



def calculate_position(
        cycle,
        smash,
        emotion
):


    # Money-cycle facts use seven explicit stages.  Prefer that field over
    # the legacy coarse cycle stage so all update/backfill/read-only paths
    # produce the same exact position recommendation.
    stage = _get(cycle, "fund_cycle_stage", "") or _get(cycle, "stage", "")


    smash_score=_float(
        _get(
            smash,
            "score",
            0
        )
    )


    # =========================
    # 仓位
    # =========================


    fund_positions = {
        "深度反击": "90%",
        "启动进攻": "80%",
        "均衡参与": "70%",
        "动能减弱": "50%",
        "防御减仓": "30%",
        "退潮警戒": "10%",
        "脉冲尾声": "1%",
    }
    if stage in fund_positions:
        position = fund_positions[stage]
    elif stage=="退潮阶段":

        position="10%-20%"

    elif stage=="冰点阶段":

        position="10%-20%"

    elif stage=="弱修复阶段":

        position="20%-30%"

    elif stage=="修复阶段":

        position="30%-40%"

    elif stage=="活跃阶段":

        position="40%-50%"

    elif stage=="高潮阶段":

        position="50%-70%"

    else:

        position="20%-30%"



    # =========================
    # 风险
    # =========================


    if stage in ("深度反击", "退潮警戒", "退潮阶段"):

        risk="★★★★★"

    elif stage=="冰点阶段":

        risk="★★★★★"

    elif stage in ("启动进攻", "防御减仓", "弱修复阶段"):

        risk="★★★★☆"

    elif stage in ("均衡参与", "修复阶段"):

        risk="★★★☆☆"

    elif stage in ("动能减弱", "活跃阶段"):

        risk="★★☆☆☆"

    elif stage in ("脉冲尾声", "高潮阶段"):

        risk="★★★☆☆"

    else:

        risk="★★★☆☆"



    # =========================
    # 策略
    # =========================


    if stage in ("深度反击", "退潮警戒", "退潮阶段"):

        strategy=(
            "高位亏钱效应明显，避免接力，"
            "仅观察低位机会。"
        )

    elif stage in ("启动进攻", "防御减仓", "弱修复阶段"):

        strategy=(
            "等待核心股确认，"
            "轻仓参与修复机会。"
        )

    elif stage in ("均衡参与", "修复阶段"):

        strategy=(
            "关注情绪回暖方向，"
            "控制仓位参与。"
        )

    elif stage in ("脉冲尾声", "高潮阶段"):

        strategy=(
            "核心龙头持股为主，"
            "注意高潮分歧风险。"
        )

    else:

        strategy=(
            "控制仓位，等待市场方向确认。"
        )


    return {

        "position":position,

        "risk":risk,

        "strategy":strategy

    }
