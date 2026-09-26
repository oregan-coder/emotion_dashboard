# -*- coding: utf-8 -*-

"""
============================================================
A股打板情绪仪表盘 V3.0.12

报告生成模块

修复：
1. 多模块字段兼容
2. 历史数据显示异常
3. float板数格式
4. 防止字段不存在导致崩溃

============================================================
"""

from datetime import datetime



def safe_get(obj, key, default=None):

    """
    安全读取对象字段

    支持：
    dict
    class对象
    pandas记录
    """

    if obj is None:

        return default


    if isinstance(obj, dict):

        return obj.get(
            key,
            default
        )


    return getattr(
        obj,
        key,
        default
    )



def safe_number(value, default=0):

    try:

        return float(value)

    except:

        return default



def safe_int(value, default=0):

    try:

        return int(float(value))

    except:

        return default



def format_board(value):

    return f"{safe_int(value)}板"



def format_percent(value):

    return f"{safe_number(value):.2f}%"



def get_history_value(row, key):

    """
    历史CSV字段兼容
    """

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


    for k in keys:

        value=safe_get(
            row,
            k,
            None
        )

        if value is not None:

            return value


    return 0



def get_feedback(
        smash,
        emotion
):

    """
    高位反馈兼容

    优先：
    emotion

    其次：
    smash
    """

    for obj in [
        emotion,
        smash
    ]:

        for key in [
            "high_feedback",
            "high_loss_feedback",
            "feedback"
        ]:

            value=safe_get(
                obj,
                key,
                None
            )

            if value:

                return value


    return "暂无"



def print_line():

    print("-"*60)



def build_report(

        version,

        date,

        previous_date,

        market,

        limit_up,

        limit_down,

        open_board,

        smash,

        emotion,

        cycle,

        position

):


    print()

    print("="*60)

    print(
        f"A股打板情绪仪表盘 V{version}"
    )

    print("="*60)


    print()

    print(
        f"监测交易日：{date}"
    )

    print(
        f"比较昨日  ：{previous_date}"
    )

    print(
        "更新时间  ：",
        datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )


    print()

    print_line()


    # ==========================
    # 市场广度
    # ==========================


    print()

    print(
        "【市场广度】"
    )

    print()


    up=0
    down=0


    if hasattr(
        market,
        "columns"
    ):

        if "涨跌幅" in market.columns:

            up=len(
                market[
                    market["涨跌幅"]>0
                ]
            )

            down=len(
                market[
                    market["涨跌幅"]<0
                ]
            )


    print(
        f"上涨：{up}  下跌：{down}  平盘：{len(market)-up-down}"
    )


    print()

    print_line()


    # ==========================
    # 涨停生态
    # ==========================


    print()

    print(
        "【涨停生态】"
    )

    print()


    print(
        f"涨停数量：{len(limit_up)}"
    )

    print(
        f"炸板数量：{len(open_board)}"
    )

    print(
        f"炸板率  ：{format_percent(safe_get(smash,'break_rate',0))}"
    )

    print(
        f"跌停数量：{len(limit_down)}"
    )


    print()

    print_line()
    # ==========================
    # 连板梯队
    # ==========================


    print()

    print(
        "【连板梯队】"
    )

    print()


    highest = safe_get(
        smash,
        "highest_board",
        0
    )


    print(
        "最高连板："
    )

    print()

    print(
        format_board(
            highest
        )
    )


    print()


    print(
        "首板/二板/三板："
    )

    print()


    print(
        f"{safe_get(smash,'first_board',0)} / "
        f"{safe_get(smash,'second_board',0)} / "
        f"{safe_get(smash,'third_board',0)}"
    )


    print()


    print(
        "四板/五板："
    )

    print()


    print(
        f"{safe_get(smash,'fourth_board',0)} / "
        f"{safe_get(smash,'fifth_board',0)}"
    )


    print()


    print(
        "高位断板率："
    )

    print()


    print(
        format_percent(
            safe_get(
                smash,
                "break_rate",
                0
            )
        )
    )


    print()


    print(
        "高位反馈："
    )

    print()


    print(
        get_feedback(
            smash,
            emotion
        )
    )


    print()

    print_line()



    # ==========================
    # 砸盘情绪
    # ==========================


    print()

    print(
        "【砸盘情绪】"
    )

    print()


    print(
        f"二板→三板       {format_percent(safe_get(smash,'rate23',0))}"
    )

    print(
        f"三板→四板       {format_percent(safe_get(smash,'rate34',0))}"
    )

    print(
        f"四板→五板       {format_percent(safe_get(smash,'rate45',0))}"
    )

    print(
        f"五板→六板       {format_percent(safe_get(smash,'rate56',0))}"
    )


    print()


    print(
        "砸盘分数："
    )

    print()


    print(
        f"{safe_number(safe_get(smash,'score',0)):.2f}/10"
    )


    print()


    print(
        "砸盘状态："
    )

    print()


    print(
        safe_get(
            smash,
            "status",
            "暂无"
        )
    )


    print()


    print(
        "最高板："
    )

    print()


    print(
        format_board(
            highest
        )
    )


    print()


    print(
        "最高板股票："
    )

    print()


    print(
        safe_get(
            smash,
            "highest_stock",
            "暂无"
        )
    )


    print()

    print_line()



    # ==========================
    # 五日情绪周期
    # ==========================


    print()

    print(
        "【五日情绪周期】"
    )

    print()


    print(
        "日期        情绪分      最高板"
    )


    history = safe_get(
        cycle,
        "history",
        []
    )


    for row in history[-5:]:


        d = get_history_value(
            row,
            "date"
        )


        score = safe_number(
            get_history_value(
                row,
                "emotion_score"
            )
        )


        board = safe_int(
            get_history_value(
                row,
                "highest_board"
            )
        )


        print(
            f"{d}   {score:.2f}分   {board}板"
        )


    print()

    print_line()



    # ==========================
    # 周期判断
    # ==========================


    print()

    print(
        "【周期判断】"
    )

    print()


    print(
        "情绪周期："
    )

    print()


    print(
        safe_get(
            cycle,
            "emotion_cycle",
            "暂无"
        )
    )


    print()


    print(
        "空间周期："
    )

    print()


    print(
        safe_get(
            cycle,
            "height_cycle",
            "暂无"
        )
    )


    print()


    print(
        "综合周期："
    )

    print()


    print(
        safe_get(
            cycle,
            "comprehensive",
            "暂无"
        )
    )


    print()


    print(
        "趋势："
    )

    print()


    print(
        safe_get(
            cycle,
            "trend",
            "暂无"
        )
    )


    print()


    print(
        "说明："
    )

    print()


    print(
        safe_get(
            cycle,
            "description",
            "暂无"
        )
    )


    print()

    print_line()



    # ==========================
    # 仓位建议
    # ==========================


    print()

    print(
        "【仓位建议】"
    )

    print()


    print(
        "建议仓位："
    )

    print()


    print(
        safe_get(
            position,
            "position",
            "暂无"
        )
    )


    print()


    print(
        "风险等级："
    )

    print()


    print(
        safe_get(
            position,
            "risk",
            "暂无"
        )
    )


    print()


    print(
        "操作策略："
    )

    print()


    print(
        safe_get(
            position,
            "strategy",
            "暂无"
        )
    )


    print()

    print_line()



    # ==========================
    # 最终结论
    # ==========================


    print()

    print(
        "【最终周期结论】"
    )

    print()


    print(
        safe_get(
            cycle,
            "stage",
            "暂无"
        )
    )


    print()


    print(
        safe_get(
            cycle,
            "description",
            "暂无"
        )
    )


    print()

    print("="*60)
