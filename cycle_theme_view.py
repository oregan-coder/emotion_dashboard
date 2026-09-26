# -*- coding: utf-8 -*-
"""
Phase2-03A-R1: 情绪周期与主线观察台视图模型
从web_snapshot.json投影研究页面所需的数据结构，不修改原始快照。
R1修复：G2市场指标保留原定义与核验状态；G3候选字段证据完整保留；五步与样本关联。
"""
import json
from pathlib import Path
from snapshot_loader import load_validation_data, get_config


# 五阶段参考（来自用户资料，仅作参考框架，不做阶段判定）
PHASE_REFERENCE = [
    {
        "phase": "冰点",
        "order": 1,
        "source_focus": "高度受压、负反馈、转折",
        "observable_clues": ["最高板", "晋级/断板/炸板表现"],
        "missing_conditions": ["同口径连续序列", "跌停及昨日涨停次日跌停成员", "可执行阈值"],
        "assessment": "NOT_EVALUATED",
    },
    {
        "phase": "启动",
        "order": 2,
        "source_focus": "新催化、首日批量首板",
        "observable_clues": ["全市场首板数量（仅作背景）"],
        "missing_conditions": ["日期化消息与题材成员", "题材首日识别", "开盘时间窗"],
        "assessment": "NOT_EVALUATED",
    },
    {
        "phase": "发酵/主升",
        "order": 3,
        "source_focus": "高度突破、完整梯队、中军参与",
        "observable_clues": ["全市场连板分布", "最高板"],
        "missing_conditions": ["题材梯队", "此前高度压制", "容量中军及放量基准"],
        "assessment": "NOT_EVALUATED",
    },
    {
        "phase": "高潮",
        "order": 4,
        "source_focus": "扩散、后排补涨、缩量加速",
        "observable_clues": ["二板封板时点/金额等记录"],
        "missing_conditions": ["题材内扩散", "跨日量能与一致性证据"],
        "assessment": "NOT_EVALUATED",
    },
    {
        "phase": "退潮",
        "order": 5,
        "source_focus": "高位负反馈与中位跌停扩散",
        "observable_clues": ["昨日高位股断板率（背景）"],
        "missing_conditions": ["断板后实际跌幅/跌停", "题材与中位母体", "资料'面率'的定义"],
        "assessment": "NOT_EVALUATED",
    },
]

# 主线五步参考（R1: observations改为空，实际观测由build_theme_steps_with_sample动态生成）
THEME_STEPS_TEMPLATE = [
    {
        "step": 1,
        "name": "消息级别",
        "purpose": "观察催化消息的级别和来源",
        "reference_note": "需要日期化直接消息及级别定义",
        "missing_evidence": ["缺日期化直接消息及级别定义"],
        "assessment": "UNKNOWN",
        "time_scope": "T_CLOSE",
    },
    {
        "step": 2,
        "name": "首日异动",
        "purpose": "观察题材首日批量首板和时间窗",
        "reference_note": "关联二板样本的首次封板时间（这不是首板潮，只是二板样本的封板记录）",
        "missing_evidence": ["缺完整日期化题材成员", "首日/时间窗", "板块指数与量能基准"],
        "assessment": "UNKNOWN",
        "time_scope": "T_CLOSE",
    },
    {
        "step": 3,
        "name": "容量中军",
        "purpose": "观察题材中军的市值和成交额",
        "reference_note": "关联样本流通市值、成交额（单位：元/CNY）；不自动把大市值样本定为中军",
        "missing_evidence": ["不是完整题材样本", "缺中军身份", "总/流通市值口径及参与基准"],
        "assessment": "UNKNOWN",
        "time_scope": "T_CLOSE",
    },
    {
        "step": 4,
        "name": "老龙异动",
        "purpose": "观察题材老龙的异动和此前行情",
        "reference_note": "缺对应题材、对应日期的老龙身份及此前行情；全市场最高板不能代替",
        "missing_evidence": ["缺对应题材、对应日期的老龙身份及此前行情", "全市场最高板不能代替"],
        "assessment": "UNKNOWN",
        "time_scope": "T_CLOSE",
    },
    {
        "step": 5,
        "name": "次日溢价验证",
        "purpose": "T+1验证龙头溢价、首板留存、中军负反馈",
        "reference_note": "本包无对应次日反馈，不得填0或完成确认",
        "missing_evidence": ["本包无对应次日反馈", "不得填0或完成确认"],
        "assessment": "UNKNOWN",
        "time_scope": "T_PLUS_1",
    },
]


def _extract_field_value(field):
    """从observed_fields的字段中提取value，支持dict和标量两种格式。"""
    if isinstance(field, dict):
        return field.get("value")
    return field


def _extract_field_evidence(field):
    """R2 B1: 完整保留原字段字典所有键，不用9字段白名单裁切。
    value/status/asof_status/unit/provider/endpoint/source_field/retrieved_at/
    event_time/public_time/published_at/note以及concepts的source/raw_concepts等保持原值。
    null仍为缺失；不造时间、不把抓取时间当公开时间。"""
    if isinstance(field, dict):
        # 完整复制原字典所有键，不做白名单裁切
        evidence = dict(field)
        # 确保核心键存在（原值为None也保留缺失语义）
        for key in ["value", "status", "asof_status", "unit", "provider",
                     "endpoint", "source_field", "retrieved_at", "event_time",
                     "public_time", "published_at", "note"]:
            if key not in evidence:
                evidence[key] = None
        return evidence
    return {"value": field, "status": None, "asof_status": None, "unit": None,
            "provider": None, "endpoint": None, "source_field": None, "retrieved_at": None,
            "event_time": None, "public_time": None, "published_at": None, "note": None}


def build_candidate_with_evidence(c):
    """构建带完整字段证据的候选股对象。"""
    observed = c.get("observed_fields", {})
    candidate = {
        "ts_code": c.get("ts_code"),
        "name": c.get("name"),
        "trade_date": c.get("trade_date"),
        "is_effective": c.get("is_effective"),  # R2 B1: 不默认true，原值为None表示未定义
        "fields": {},
    }
    # 保留所有字段的完整证据
    for field_name, field_value in observed.items():
        candidate["fields"][field_name] = _extract_field_evidence(field_value)
    # 同时提供便捷的value访问（用于表格显示）
    candidate["values"] = {k: v["value"] for k, v in candidate["fields"].items()}
    return candidate


def build_theme_steps_with_sample(selected_concept=None, concept_members=None, all_candidates=None):
    """
    R1 G3: 构建五步观察，将"已有线索"与实际观测分开。
    选择概念后，第二步关联首次封板记录，第三步关联流通市值、成交额。
    """
    steps = []
    for template in THEME_STEPS_TEMPLATE:
        step = dict(template)
        step["observations"] = []  # 实际观测，默认空
        step["sample_evidence"] = None  # 关联的样本证据

        if selected_concept and concept_members:
            step["selected_concept"] = selected_concept
            step["sample_count"] = len(concept_members)

            if step["step"] == 2:
                # 第二步：关联首次封板记录
                seal_records = []
                for m in concept_members:
                    fields = m.get("fields", {})
                    first_seal = fields.get("first_seal_time", {})
                    last_seal = fields.get("last_seal_time", {})
                    open_break = fields.get("open_break_count", {})
                    seal_records.append({
                        "ts_code": m.get("ts_code"),
                        "name": m.get("name"),
                        "first_seal_time": first_seal.get("value"),
                        "first_seal_status": first_seal.get("status"),
                        "last_seal_time": last_seal.get("value"),
                        "open_break_count": open_break.get("value"),
                        "evidence_ref": "fields.first_seal_time",
                    })
                step["sample_evidence"] = {
                    "type": "FIRST_SEAL_RECORDS",
                    "records": seal_records,
                    "note": "二板样本的首次封板时间，不是首板潮；缺完整日期化题材成员无法判断首日异动",
                }
                step["observations"] = [f"关联{len(seal_records)}只样本的首次封板记录（详见样本证据）"]

            elif step["step"] == 3:
                # 第三步：关联流通市值、成交额
                cap_records = []
                for m in concept_members:
                    fields = m.get("fields", {})
                    float_cap = fields.get("float_market_cap_cny", {})
                    amount = fields.get("amount_cny", {})
                    volume = fields.get("volume_shares", {})
                    cap_records.append({
                        "ts_code": m.get("ts_code"),
                        "name": m.get("name"),
                        "float_market_cap_cny": float_cap.get("value"),
                        "float_market_cap_unit": "元/CNY",
                        "float_market_cap_status": float_cap.get("status"),
                        "amount_cny": amount.get("value"),
                        "amount_unit": "元/CNY",
                        "amount_status": amount.get("status"),
                        "volume_shares": volume.get("value"),
                        "volume_unit": "股",
                        "evidence_ref": "fields.float_market_cap_cny / fields.amount_cny",
                    })
                step["sample_evidence"] = {
                    "type": "MARKET_CAP_AND_AMOUNT",
                    "records": cap_records,
                    "note": "金额单位为元/CNY；不自动把大市值样本定为中军；缺中军身份和完整题材样本",
                }
                step["observations"] = [f"关联{len(cap_records)}只样本的流通市值和成交额（详见样本证据）"]

        elif all_candidates and len(all_candidates) > 0:
            # 未选择概念时，显示全样本事实
            step["sample_scope"] = "ALL_SECOND_BOARD_SAMPLE"
            step["sample_count"] = len(all_candidates)
            if step["step"] == 2:
                step["observations"] = [f"全部{len(all_candidates)}只二板样本的首次封板记录可在下方样本表查看"]
            elif step["step"] == 3:
                step["observations"] = [f"全部{len(all_candidates)}只二板样本的流通市值和成交额可在下方样本表查看"]
        else:
            # 0候选空态
            step["sample_scope"] = "NO_CANDIDATES"
            step["sample_count"] = 0

        steps.append(step)
    return steps


def build_cycle_theme_view(snapshot_data, load_status="OK", load_errors=None):
    """
    从快照数据构建周期与主线研究页视图模型。
    返回dict，包含设计稿要求的所有区块。
    R1: G2市场指标保留原定义与核验状态；G3候选字段证据完整保留。
    """
    if load_errors is None:
        load_errors = []

    # 如果加载失败，返回错误结构
    if load_status != "OK" or not snapshot_data:
        return {
            "provenance": {
                "trade_date": None,
                "previous_date": None,
                "snapshot_id": None,
                "content_hash": None,
                "data_version": None,
                "frozen_source": None,
                "load_status": load_status,
                "load_errors": load_errors,
            },
            "error": True,
            "error_type": load_status,
            "error_message": "; ".join(load_errors) if load_errors else "数据加载失败",
        }

    trade_date = snapshot_data.get("trade_date")
    previous_date = snapshot_data.get("previous_date")
    snapshot_id = snapshot_data.get("snapshot_id")
    content_hash = snapshot_data.get("content_hash")
    version = snapshot_data.get("version")

    # 1. provenance
    provenance = {
        "trade_date": trade_date,
        "previous_date": previous_date,
        "snapshot_id": snapshot_id,
        "content_hash": content_hash,
        "data_version": version,
        "frozen_source": "data/web_snapshot.json（冻结历史样本）",
        "observation_perspective": "T_CLOSE",
        "perspective_note": "只用于研究视角，不宣称所有数据在T日实际可获得",
        "historical_availability_verified": False,
        "historical_availability_note": "历史数据可获得时点尚未验证",
    }

    # 2. market_context
    market_overview = snapshot_data.get("market_overview", {})
    market_metrics = snapshot_data.get("market_metrics", {})

    # R1 G2: 四个市场指标 - 直接保留原metric的所有字段，不重写definition
    cohorts = []
    # 将list转为dict方便查找
    metrics_dict = {}
    if isinstance(market_metrics, list):
        for m in market_metrics:
            if isinstance(m, dict) and m.get("id"):
                metrics_dict[m["id"]] = m
    elif isinstance(market_metrics, dict):
        metrics_dict = market_metrics

    expected_metric_ids = ["high_board_fail_rate", "prior_limitup_continue_rate",
                            "two_to_three_rate", "failed_limitup_rate"]

    for metric_id in expected_metric_ids:
        metric = metrics_dict.get(metric_id, {})
        # R1 G2: 主显示取经过核验的calculated_value；原reported_value单列为"报告值"
        calculated_value = metric.get("calculated_value")
        reported_value = metric.get("reported_value")
        calculation_verified = metric.get("calculation_verified")
        source_verified = metric.get("source_verified")

        # R2 A2: 主显示值：只有calculation_verified为true且calculated_value非空时才用复算值
        # calculation_verified不为true时，primary_value为null，主区显示未核实
        # 原计算值/报告值在详情标为未核验值，不用value兼容字段回退为正式主值
        if calculation_verified is True and calculated_value is not None:
            primary_value = calculated_value
            primary_value_status = "CALCULATED_VERIFIED"
        else:
            primary_value = None
            primary_value_status = "UNVERIFIED" if calculated_value is None else "CALCULATED_NOT_VERIFIED_NULL_PRIMARY"

        # 03B-01 A1: 标签诊断按指标独立初始化
        # 每个指标开始时初始化自己的诊断，缺值无法比较时保持空诊断
        # 不能使用上一指标状态，不能在最外层捕获异常后把整个研究结果清空
        value_mismatch = None
        label_numeric_conflict = None
        report_value_status = metric.get("report_value_status")
        if reported_value is not None and calculated_value is not None:
            try:
                rep = float(reported_value)
                calc = float(calculated_value)
                # 按报告值的小数位数比较：报告值精度内一致不算冲突
                rep_str = str(reported_value)
                if '.' in rep_str:
                    decimals = len(rep_str.split('.')[1])
                else:
                    decimals = 0
                tolerance = 0.5 * (10 ** (-decimals)) if decimals > 0 else 0.5
                numeric_mismatch = abs(rep - calc) > tolerance
                # 标签与数值一致性检查
                if report_value_status == "MATCH" and numeric_mismatch:
                    # 标签说MATCH但数值实际不一致，记录矛盾
                    label_numeric_conflict = "来源标签为MATCH，但数值实际存在差异"
                elif report_value_status == "MISMATCH" and not numeric_mismatch:
                    # 标签说MISMATCH但数值在精度内一致，记录矛盾
                    label_numeric_conflict = "来源标签为MISMATCH，但数值在精度内一致"
                # 最终以数值比较为准，标签只作为参考信息
                if numeric_mismatch:
                    value_mismatch = {
                        "reported_value": reported_value,
                        "calculated_value": calculated_value,
                        "report_value_status": report_value_status,
                        "numeric_mismatch": True,
                        "label_numeric_conflict": label_numeric_conflict,
                        "comparison_tolerance": "按报告值精度比较（%s）" % tolerance,
                        "note": "报告值与复算值不一致，主显示采用复算值",
                    }
            except (ValueError, TypeError):
                # 非数值无法比较，保留原值和空诊断
                pass

        cohort = {
            "id": metric_id,
            "name": metric.get("name", metric_id),
            # R1 G2: 保留原definition，不重写
            "definition": metric.get("definition"),
            # R1 G2: 主显示值和状态
            "primary_value": primary_value,
            "primary_value_status": primary_value_status,
            "calculated_value": calculated_value,
            "reported_value": reported_value,
            "value_mismatch": value_mismatch,
            # R4-L2: 标签矛盾独立输出，不依赖numeric_mismatch
            # MISMATCH+0/0时numeric_mismatch=false但标签矛盾仍需保留
            "label_numeric_conflict": label_numeric_conflict,
            # R2 A2: 不用value兼容字段回退为正式主值
            # 未核验时value也为null，详情中标为未核验值
            "value": primary_value,
            # 分子分母和成员数组
            "numerator": metric.get("numerator"),
            "denominator": metric.get("denominator"),
            "numerator_codes": metric.get("numerator_codes"),
            "denominator_codes": metric.get("denominator_codes"),
            # R1 G2: 核验状态
            "status": metric.get("status"),
            "source_verified": source_verified,
            "calculation_verified": calculation_verified,
            "report_value_status": metric.get("report_value_status"),
            "cohort_match": metric.get("cohort_match"),
            # R1 G2: 正确字段名是cohort_mismatch_detail，不是cohort_match_detail
            "cohort_mismatch_detail": metric.get("cohort_mismatch_detail"),
            "cohort_match_detail": metric.get("cohort_match_detail"),  # 保留兼容
            "validation_error": metric.get("validation_error"),
            # R2 A4: 保留真实来源字段，不重新选择少数键再次丢字段
            # source_file/source_field/source_note等键完整传递
            "source": metric.get("source"),
            "source_file": metric.get("source_file"),
            "source_field": metric.get("source_field"),
            "source_note": metric.get("source_note"),
            "source_files": metric.get("source_files"),
            "provider": metric.get("provider"),
            "endpoint": metric.get("endpoint"),
            # 未知原因
            "unknown_reason": metric.get("unknown_reason"),
        }
        cohorts.append(cohort)

    market_context = {
        "limit_up_count": market_overview.get("limit_up_count"),
        "failed_limit_up_count": market_overview.get("failed_limit_up_count"),
        "second_board_count": market_overview.get("second_board_count"),
        "max_board": market_overview.get("max_board"),
        "max_board_stock": market_overview.get("max_board_stock"),
        "max_board_stocks": market_overview.get("max_board_stocks"),
        "board_distribution": market_overview.get("board_distribution"),
        "limit_up_codes": market_overview.get("limit_up_codes"),
        "failed_limit_up_codes": market_overview.get("failed_limit_up_codes"),
        "calculated_from_raw_pools": market_overview.get("calculated_from_raw_pools"),
        "source_files": market_overview.get("source_files"),
        "cohorts": cohorts,
    }

    # 3. phase_inference（未实现）
    phase_inference = {
        "status": "NOT_IMPLEMENTED",
        "label": None,
        "reason": "阶段识别算法尚未实现，不根据最高板或单个比例猜测阶段",
        "current_phase": "未判定",
    }

    # 4. theme_inference（未实现）
    theme_inference = {
        "status": "NOT_IMPLEMENTED",
        "confirmed_theme": None,
        "reason": "主线确认算法尚未实现，缺日期化题材证据，不得由静态概念产生确认",
    }

    # 5. phase_reference（五阶段参考）
    phase_reference = {
        "phases": PHASE_REFERENCE,
        "source_kind": "USER_REFERENCE",
        "note": "五阶段只是参考框架，不表示每次行情必然按顺序转移",
        "ambiguity_note": "旧dashboard使用'冰点/弱修复/震荡/高潮/退潮'并将未知兜底为震荡，新页不复用这套枚举/兜底",
    }

    # 7. static_clues（静态概念线索与样本）
    # R1 G3: 候选字段保留完整证据对象
    candidates_raw = snapshot_data.get("candidates", [])
    # R3-1: 移除基于is_effective的额外过滤
    # 研究页仅使用共享loader返回的身份/日期合法候选
    # is_effective可作为原始未定义元信息保留，但不能新增母体筛选规则
    # 身份合格不表示字段在T日可用，继续按原字段status/asof_status表达
    valid_candidates = []
    for c in candidates_raw:
        if c.get("ts_code"):
            valid_candidates.append(build_candidate_with_evidence(c))
    sample_count = len(valid_candidates)

    # R1 G3: 收集所有静态概念 - 按源顺序去重，不按样本人数排序
    concept_map = {}  # 保持插入顺序
    concept_order = []
    for c in valid_candidates:
        fields = c.get("fields", {})
        concepts_field = fields.get("concepts", {})
        concept_value = concepts_field.get("value") if isinstance(concepts_field, dict) else concepts_field
        if isinstance(concept_value, list):
            for concept_name in concept_value:
                if concept_name not in concept_map:
                    concept_map[concept_name] = []
                    concept_order.append(concept_name)
                concept_map[concept_name].append(c)

    # R1 G3: 按源顺序，不排序
    concepts_list = []
    for concept_name in concept_order:
        members = concept_map[concept_name]
        concepts_list.append({
            "name": concept_name,
            "member_count": len(members),
            "members": members,  # R1 G3: members现在是带完整fields的候选对象
        })

    # R1 G3: 候选隔离和错误 - 使用isolated_records和candidate_errors
    isolated_records = snapshot_data.get("isolated_records", [])
    candidate_conflicts = snapshot_data.get("candidate_conflicts", [])
    candidate_errors = snapshot_data.get("candidate_errors", [])

    static_clues = {
        "scope": "SECOND_BOARD_SAMPLE",
        "sample_count": sample_count,
        "sample_note": "只覆盖本次二板样本，不是全市场题材成员",
        "membership_kind": "STATIC_F10",
        "historical_validity": "UNVERIFIED_HISTORICAL",
        "concepts": concepts_list,
        # R1 G3: 完整的隔离和错误信息
        "isolated_records": isolated_records,
        "candidate_conflicts": candidate_conflicts,
        "candidate_errors": candidate_errors,
        # 兼容旧字段
        "candidate_isolation": candidate_conflicts,
    }

    # 6. theme_steps（主线五步）- R1 G3: 动态构建，默认未选择概念
    theme_steps = build_theme_steps_with_sample(
        selected_concept=None,
        concept_members=None,
        all_candidates=valid_candidates if sample_count > 0 else None,
    )

    # 8. next_session（次日观察）
    next_session = {
        "observation_status": "NOT_OBSERVED",
        "evaluation": "UNKNOWN",
        "note": "本包未提供对应次日反馈，不得使用当前时间判断是否完成",
        "pending_items": [
            {"name": "龙头候选溢价", "status": "UNKNOWN"},
            {"name": "昨日首板留存", "status": "UNKNOWN"},
            {"name": "中军负反馈", "status": "UNKNOWN"},
        ],
    }

    # 9. implementation_status
    implementation_status = {
        "page_function": "研究资料与事实的组织方式",
        "new_policy_implemented": False,
        "new_policy_status": snapshot_data.get("new_policy_status", "NOT_IMPLEMENTED"),
        "phase_inference_implemented": False,
        "theme_inference_implemented": False,
        "legacy_replay_status": snapshot_data.get("legacy_replay_verification", {}).get("status", "BLOCKED"),
        "legacy_replay_reason": snapshot_data.get("legacy_replay_verification", {}).get("reason", ""),
        "old_dashboard_date": "09-07（旧模型结果，与本页09-04冻结样本不同）",
    }

    # 10. gaps_and_references（待补证据与资料说明）
    gaps = [
        {"name": "日期化消息与题材证据契约", "purpose": "确认主线第一步消息级别", "status": "MISSING"},
        {"name": "同口径连续序列", "purpose": "五阶段判定需要连续数据", "status": "MISSING"},
        {"name": "事件发生/公开/取得时点", "purpose": "区分T日可获得与事后回填", "status": "MISSING"},
        {"name": "T+1反馈母体", "purpose": "次日溢价验证需要完整母体", "status": "MISSING"},
        {"name": "阈值假设及验证方案", "purpose": "五阶段和五步的判定阈值", "status": "NOT_DEFINED"},
        {"name": "完整39只涨停股概念映射", "purpose": "当前只有6只二板样本的静态概念", "status": "MISSING"},
    ]

    data_quality = snapshot_data.get("data_quality", {})
    phase1_status = snapshot_data.get("phase1_status", {})

    return {
        "provenance": provenance,
        "market_context": market_context,
        "phase_inference": phase_inference,
        "theme_inference": theme_inference,
        "phase_reference": phase_reference,
        "theme_steps": theme_steps,
        "static_clues": static_clues,
        "next_session": next_session,
        "implementation_status": implementation_status,
        "gaps": gaps,
        "data_quality": data_quality,
        "phase1_status": phase1_status,
        "error": False,
    }


def load_cycle_theme_data(requested_date=None, config=None):
    """
    加载周期与主线研究页数据。
    复用共享快照校验，不重复实现源选择与校验。
    """
    if config is None:
        config = get_config()

    data, load_status, errors = load_validation_data(config=config, requested_date=requested_date)
    view = build_cycle_theme_view(data, load_status, errors)
    return view, load_status, errors
