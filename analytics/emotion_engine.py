# -*- coding: utf-8 -*-

"""
============================================================
A股打板情绪仪表盘 V3.0.3
情绪评分引擎

功能：
1. 计算市场情绪分数
2. 判断情绪阶段
3. 输出高度周期状态
============================================================
"""

from dataclasses import dataclass


@dataclass
class EmotionResult:
    score: float
    cycle_stage: str
    height_stage: str
    detail: dict
    # P03A: 数据状态标记
    status: str = "VALID"  # VALID / DATA_PENDING / PARTIAL
    missing_fields: list = None  # 缺失的必需字段列表

    def __post_init__(self):
        if self.missing_fields is None:
            self.missing_fields = []


def safe_float(value, default=0):
    try:
        return float(value)
    except Exception:
        return default


def limit_up_score(limit_up):
    """
    涨停生态评分 25分
    P03A R3.1: None返回None，不默认给分
    P03A R3.1 V3: 拒绝Python/numpy bool，不变成1
    """
    if limit_up is None:
        return None
    # 拒绝Python/numpy bool
    try:
        import numpy as np
        if isinstance(limit_up, (bool, np.bool_)):
            return None
    except ImportError:
        if isinstance(limit_up, bool):
            return None
    try:
        import math
        limit_up = float(limit_up)
        if not math.isfinite(limit_up):
            return None
    except (ValueError, TypeError):
        return None

    if limit_up >= 80:
        return 25

    if limit_up >= 50:
        return 22

    if limit_up >= 30:
        return 18

    if limit_up >= 15:
        return 12

    return 5


def ladder_score(highest_board):
    """
    连板高度评分 20分
    P03A R3.1 V2: None/异常返回None，不默认给分
    """
    if highest_board is None:
        return None
    # 拒绝Python/numpy bool
    try:
        import numpy as np
        if isinstance(highest_board, (bool, np.bool_)):
            return None
    except ImportError:
        if isinstance(highest_board, bool):
            return None
    try:
        import math
        highest_board = float(highest_board)
        if not math.isfinite(highest_board):
            return None
        highest_board = int(highest_board)
    except (ValueError, TypeError):
        return None

    if highest_board >= 8:
        return 20

    if highest_board >= 6:
        return 17

    if highest_board >= 4:
        return 14

    if highest_board >= 3:
        return 10

    return 5


def promotion_score(rate12):
    """
    首板晋级评分 15分
    P03A R3.1 V2: None/异常返回None，不默认给分
    """
    if rate12 is None:
        return None
    try:
        import numpy as np
        if isinstance(rate12, (bool, np.bool_)):
            return None
    except ImportError:
        if isinstance(rate12, bool):
            return None
    try:
        import math
        rate12 = float(rate12)
        if not math.isfinite(rate12):
            return None
    except (ValueError, TypeError):
        return None

    if rate12 >= 40:
        return 15

    if rate12 >= 25:
        return 12

    if rate12 >= 15:
        return 8

    return 3


def previous_limit_score(rate):
    """
    昨日涨停表现 15分

    P03A: rate=None时返回None，不默认给8分
    P03A R2: 异常字符串/结构不默认转0得8分
    """

    # P03A: None不转为0，缺失数据返回None
    if rate is None:
        return None

    # P03A: bool不转为数值（True!=1）
    # P03A R3.1: 同时拒绝numpy bool
    try:
        import numpy as np
        if isinstance(rate, (bool, np.bool_)):
            return None
    except ImportError:
        if isinstance(rate, bool):
            return None

    # P03A R2: 异常字符串/字典/列表等非数值类型不默认转0
    if isinstance(rate, (dict, list, tuple)):
        return None

    # P03A R2: 使用不返回默认值的安全转换
    try:
        import math
        rate_float = float(rate)
        if not math.isfinite(rate_float):
            return None
    except (ValueError, TypeError):
        return None

    if rate_float >= 5:
        return 15

    if rate_float >= 2:
        return 12

    if rate_float >= 0:
        return 8

    return 3


def break_score(break_rate):
    """
    炸板率评分 10分

    炸板越低越健康
    P03A R3.1: None返回None，不默认给10分
    P03A R3.1 V3: 拒绝Python/numpy bool，不变成1
    """
    if break_rate is None:
        return None
    # 拒绝Python/numpy bool
    try:
        import numpy as np
        if isinstance(break_rate, (bool, np.bool_)):
            return None
    except ImportError:
        if isinstance(break_rate, bool):
            return None
    try:
        import math
        rate = float(break_rate)
        if not math.isfinite(rate):
            return None
    except (ValueError, TypeError):
        return None

    if rate <= 20:
        return 10

    if rate <= 35:
        return 8

    if rate <= 50:
        return 5

    return 2


def height_feedback_score(loss_count):
    """
    高位反馈评分 10分
    P03A R3.1: None返回None，不默认给10分
    P03A R3.1 V3: 拒绝Python/numpy bool，不变成1
    """
    if loss_count is None:
        return None
    # 拒绝Python/numpy bool
    try:
        import numpy as np
        if isinstance(loss_count, (bool, np.bool_)):
            return None
    except ImportError:
        if isinstance(loss_count, bool):
            return None
    try:
        import math
        loss_count = float(loss_count)
        if not math.isfinite(loss_count):
            return None
        loss_count = int(loss_count)
    except (ValueError, TypeError):
        return None

    if loss_count == 0:
        return 10

    if loss_count <= 2:
        return 6

    return 2


def market_width_score(up, down):
    """
    市场宽度评分 5分
    P03A R3.1 V2: None/异常返回None，不默认给分
    """
    if up is None or down is None:
        return None
    try:
        import numpy as np
        if isinstance(up, (bool, np.bool_)) or isinstance(down, (bool, np.bool_)):
            return None
    except ImportError:
        if isinstance(up, bool) or isinstance(down, bool):
            return None
    try:
        import math
        up = float(up)
        down = float(down)
        if not math.isfinite(up) or not math.isfinite(down):
            return None
    except (ValueError, TypeError):
        return None

    if up + down == 0:
        return 2

    ratio = up / (up + down)

    if ratio >= 0.6:
        return 5

    if ratio >= 0.5:
        return 3

    return 1


def calculate_emotion(
        limit_up_count,
        highest_board,
        rate12,
        yesterday_rate,
        break_rate,
        high_loss_count,
        up_count,
        down_count
):
    """
    主情绪计算

    总分100

    P03A: 缺失必需依赖时，score=None，status=DATA_PENDING
    """

    parts = {}
    missing_fields = []

    parts["涨停生态"] = limit_up_score(
        limit_up_count
    )

    parts["连板梯队"] = ladder_score(
        highest_board
    )

    parts["晋级率"] = promotion_score(
        rate12
    )

    # P03A: 昨日表现可能为None（BK1050缺失）
    yesterday_score = previous_limit_score(
        yesterday_rate
    )
    parts["昨日表现"] = yesterday_score
    if yesterday_score is None:
        missing_fields.append("yesterday_rate(883900/local)")

    parts["炸板率"] = break_score(
        break_rate
    )

    parts["高位反馈"] = height_feedback_score(
        high_loss_count
    )

    parts["市场宽度"] = market_width_score(
        up_count,
        down_count
    )

    # P03A R3.1: 检查所有可能为None的分项
    for key, val in parts.items():
        if val is None:
            missing_fields.append(key)

    # P03A: 检查是否有缺失的必需字段
    if missing_fields:
        # 有缺失字段时，完整总分=None，保留可信分项
        score = None
        status = "DATA_PENDING"
        cycle = "待证据"
        height = judge_height(
            highest_board
        )
    else:
        # 所有必需字段都有值时，计算完整总分
        score = round(
            sum(parts.values()),
            2
        )
        status = "VALID"
        cycle = judge_cycle(
            score
        )
        height = judge_height(
            highest_board
        )

    return EmotionResult(
        score=score,
        cycle_stage=cycle,
        height_stage=height,
        detail=parts,
        status=status,
        missing_fields=missing_fields
    )


def judge_cycle(score):
    """
    情绪周期判断（V6已批准规则）
    0≤s<10：退潮
    10≤s<25：冰点
    25≤s<35：试错
    35≤s<50：启动
    50≤s<70：主升
    70≤s≤90：高潮
    90<s≤100：退潮
    90分本身仍为高潮。非法或缺失值不能当0。
    """
    import math

    # V6: 非法或缺失值不能当0，返回None
    # V7: 补numpy bool缺口，np.bool_不是Python bool的子类
    if score is None:
        return None
    if isinstance(score, bool):
        return None
    try:
        import numpy as np
        if isinstance(score, np.bool_):
            return None
    except ImportError:
        pass
    try:
        score_float = float(score)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(score_float):
        return None
    if score_float < 0 or score_float > 100:
        return None

    # V6: 新的7阶段映射
    if score_float < 10:
        return "退潮期"
    if score_float < 25:
        return "冰点期"
    if score_float < 35:
        return "试错期"
    if score_float < 50:
        return "启动期"
    if score_float < 70:
        return "主升期"
    if score_float <= 90:
        return "高潮期"
    # 90 < score <= 100
    return "退潮期"


def judge_height(highest_board):
    """
    空间高度判断
    P03A R3.1 V2: None/异常返回"待证据"，不默认给"高度压缩"
    """
    if highest_board is None:
        return "待证据"
    try:
        import numpy as np
        if isinstance(highest_board, (bool, np.bool_)):
            return "待证据"
    except ImportError:
        if isinstance(highest_board, bool):
            return "待证据"
    try:
        import math
        highest_board = float(highest_board)
        if not math.isfinite(highest_board):
            return "待证据"
        highest_board = int(highest_board)
    except (ValueError, TypeError):
        return "待证据"

    if highest_board >= 8:
        return "高度扩张"

    if highest_board >= 5:
        return "空间稳定"

    if highest_board >= 3:
        return "空间震荡"

    return "高度压缩"


def emotion_to_dict(result):
    """
    转换CSV存储格式
    """

    return {
        "emotion_score": result.score,
        "cycle_stage": result.cycle_stage,
        "height_stage": result.height_stage
    }