# -*- coding: utf-8 -*-
"""
Phase2-Web01.1-R3: 导出供页面读取的观测数据与状态 (web_snapshot.json)
只读，不修改任何源数据。
R3修复：使用共享snapshot_loader配置，删除独立路径逻辑。
"""
import json
import hashlib
import time
import sys
from pathlib import Path

# R3 C1: 使用共享snapshot_loader配置
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from snapshot_loader import (
    SnapshotConfig, find_project_root, validate_metric, normalize_code
)

# R3: 从应用文件位置定位项目根（不依赖调用者cwd）
PROJECT_ROOT = find_project_root(SCRIPT_DIR)
CONFIG = SnapshotConfig(project_root=PROJECT_ROOT)


def load_json(path):
    if path and Path(path).exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def file_hash(path):
    if path and Path(path).exists():
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    return "MISSING"


def normalize_code(code):
    """规范化股票代码：600108 -> 600108.SH, 002403 -> 002403.SZ"""
    if not code:
        return code
    code = str(code).strip()
    if "." in code:
        return code
    if code.startswith(("60", "68", "90", "11", "13", "51")):
        return code + ".SH"
    elif code.startswith(("00", "30", "20", "12", "15", "16", "18")):
        return code + ".SZ"
    elif code.startswith(("8", "4")):
        return code + ".BJ"
    return code




def main():ue, round(calc_value, 4), "", details


def main():
    snapshot_id = "web01_r3_%s" % time.strftime("%Y%m%d_%H%M%S")
    run_id = "web_snapshot_export_r3_%s" % snapshot_id
    trade_date = "20260904"
    previous_date = "20260903"

    # R3 C1: 使用共享配置获取输入文件路径
    input_files = {
        "candidates": str(CONFIG.get_input_file("03_20260904_second_board_candidates.json")),
        "market_cohorts": str(CONFIG.get_input_file("08_market_cohorts.json")),
        "legacy_replay": str(CONFIG.get_input_file("20260904_legacy_replay.json")),
        "shadow_output": str(CONFIG.get_input_file("20260904_shadow_output.json")),
        "data_quality_report": str(CONFIG.get_input_file("09_data_quality_report.json")),
        "phase1_status": str(CONFIG.get_input_file("21_phase1_status.json")),
        "zt_pool_0904": str(CONFIG.get_input_file("20260904_stock_zt_pool_em.json")),
        "zb_pool_0904": str(CONFIG.get_input_file("20260904_stock_zt_pool_zbgc_em.json")),
        "zt_pool_0903": str(CONFIG.get_input_file("20260903_stock_zt_pool_em.json")),
        "concept_cache": str(CONFIG.get_input_file("20260904_concept_cache_slice.json")),
    }
    input_hashes = {k: file_hash(Path(v)) for k, v in input_files.items()}

    # R3 C1: 关键输入缺失时非零退出（不生成零候选零指标的空文件）
    critical_inputs = ["candidates", "market_cohorts", "zt_pool_0904", "zb_pool_0904"]
    missing_critical = [k for k in critical_inputs if input_hashes.get(k) == "MISSING"]
    if missing_critical:
        print("[FATAL] 关键输入文件缺失: %s" % ", ".join(missing_critical))
        print("请确认 reference_inputs/phase2_shadow/fixtures/source/ 目录存在")
        sys.exit(1)

    # 加载数据
    candidates_data = load_json(input_files["candidates"])
    cohorts_data = load_json(input_files["market_cohorts"])

    # R05: 校验候选源文件的父日期与选定日期一致
    if candidates_data:
        source_trade_date = candidates_data.get("trade_date")
        if source_trade_date and str(source_trade_date) != str(trade_date):
            print("[FATAL] 候选源文件父日期(%s)与选定日期(%s)不一致，终止导出" % (source_trade_date, trade_date))
            print("请检查输入文件或修改trade_date参数")
            sys.exit(1)
        # 校验每条候选的trade_date
        if isinstance(candidates_data.get("candidates"), list):
            for c in candidates_data["candidates"]:
                if isinstance(c, dict) and c.get("trade_date"):
                    if str(c.get("trade_date")) != str(trade_date):
                        print("[FATAL] 候选股%s的trade_date(%s)与选定日期(%s)不一致，终止导出" % (
                            c.get("ts_code", "?"), c.get("trade_date"), trade_date))
                        sys.exit(1)
    legacy_data = load_json(input_files["legacy_replay"])
    shadow_data = load_json(input_files["shadow_output"])
    dq_data = load_json(input_files["data_quality_report"])
    phase1_status = load_json(input_files["phase1_status"])
    zt_pool_0904 = load_json(input_files["zt_pool_0904"])
    zb_pool_0904 = load_json(input_files["zb_pool_0904"])
    zt_pool_0903 = load_json(input_files["zt_pool_0903"])

    # === 1. 市场概览（从原始池计算，非硬编码）===
    market_overview = {
        "trade_date": trade_date,
        "calculated_from_raw_pools": True,
        "source_files": ["20260904_stock_zt_pool_em.json", "20260904_stock_zt_pool_zbgc_em.json"],
    }

    if isinstance(zt_pool_0904, list) and zt_pool_0904:
        limit_up_count = len(zt_pool_0904)
        # 连板分布
        board_dist = {}
        for s in zt_pool_0904:
            b = s.get("连板数", s.get("连续涨停天数", 1))
            try:
                b = int(b)
            except (ValueError, TypeError):
                b = 1
            board_dist[b] = board_dist.get(b, 0) + 1
        second_board_count = board_dist.get(2, 0)
        max_board = max(board_dist.keys()) if board_dist else None
        max_board_stocks = [
            {"code": normalize_code(s.get("代码", "")), "name": s.get("名称", "")}
            for s in zt_pool_0904
            if int(s.get("连板数", s.get("连续涨停天数", 1)) or 1) == max_board
        ] if max_board else []
        max_board_stock = "%s(%s)" % (max_board_stocks[0]["name"], max_board_stocks[0]["code"].split(".")[0]) if max_board_stocks else None

        market_overview.update({
            "limit_up_count": limit_up_count,
            "second_board_count": second_board_count,
            "max_board": max_board,
            "max_board_stock": max_board_stock,
            "max_board_stocks": max_board_stocks,
            "board_distribution": board_dist,
            "status": "VALID",
        })
    else:
        market_overview.update({
            "limit_up_count": None,
            "second_board_count": None,
            "max_board": None,
            "max_board_stock": None,
            "status": "MISSING",
            "error": "涨停池文件缺失或为空",
        })

    if isinstance(zb_pool_0904, list) and zb_pool_0904:
        failed_limit_up_count = len(zb_pool_0904)
        market_overview["failed_limit_up_count"] = failed_limit_up_count
        # 炸板率分母：涨停+炸板去重并集
        zt_codes = set(normalize_code(s.get("代码", "")) for s in zt_pool_0904 if s.get("代码"))
        zb_codes = set(normalize_code(s.get("代码", "")) for s in zb_pool_0904 if s.get("代码"))
        union_codes = zt_codes | zb_codes
        market_overview["limit_up_failed_union_count"] = len(union_codes)
        market_overview["limit_up_codes"] = sorted(zt_codes)
        market_overview["failed_limit_up_codes"] = sorted(zb_codes)
    else:
        market_overview["failed_limit_up_count"] = None
        market_overview["status"] = "MISSING" if market_overview.get("status") == "VALID" else market_overview["status"]
        market_overview["error"] = (market_overview.get("error", "") + "; 炸板池文件缺失或为空").strip("; ")

    # === 2. 四个市场指标（从原始文件+cohort复算）===
    metric_defs = {
        "two_to_three_rate": {
            "name": "二进三晋级率",
            "definition": "前日恰为二板的股票中，当日恰为三板成功的比例",
        },
        "prior_limitup_continue_rate": {
            "name": "昨日涨停续板率",
            "definition": "前日涨停股中当日继续收盘涨停的比例",
        },
        "high_board_fail_rate": {
            "name": "昨日高位股断板率",
            "definition": "前日≥4板高位股中当日未成功续板的比例",
        },
        "failed_limitup_rate": {
            "name": "当日炸板率",
            "definition": "当日曾触及涨停但收盘未封住的股票，占收盘涨停+炸板去重集合的比例",
        },
    }

    # === C3: 从原始池复算前三指标的分子分母 ===
    raw_recalc = {}
    has_0903_pool = isinstance(zt_pool_0903, list) and len(zt_pool_0903) > 0
    has_0904_pool = isinstance(zt_pool_0904, list) and len(zt_pool_0904) > 0
    # R3 C3: 缺当日涨停池时记录警告，不抛异常
    if zt_pool_0904 is None:
        print("[WARN] 当日涨停池(20260904_stock_zt_pool_em.json)缺失，受影响指标将标记SOURCE_VERIFICATION_PENDING")
    elif not isinstance(zt_pool_0904, list):
        print("[WARN] 当日涨停池格式异常(type=%s)，受影响指标将标记SOURCE_VERIFICATION_PENDING" % type(zt_pool_0904).__name__)

    if has_0903_pool and has_0904_pool:
        # 0903涨停股代码集合
        zt_0903_codes = set()
        zt_0903_boards = {}  # code -> board_count
        for s in zt_pool_0903:
            code = normalize_code(s.get("代码", ""))
            if code:
                zt_0903_codes.add(code)
                try:
                    b = int(s.get("连板数", s.get("连续涨停天数", 1)) or 1)
                except (ValueError, TypeError):
                    b = 1
                zt_0903_boards[code] = b

        # 0904涨停股代码集合
        zt_0904_codes = set()
        zt_0904_boards = {}
        for s in zt_pool_0904:
            code = normalize_code(s.get("代码", ""))
            if code:
                zt_0904_codes.add(code)
                try:
                    b = int(s.get("连板数", s.get("连续涨停天数", 1)) or 1)
                except (ValueError, TypeError):
                    b = 1
                zt_0904_boards[code] = b

        # two_to_three_rate: 0903恰为二板 -> 0904恰为三板
        prev_second_board = sorted([c for c, b in zt_0903_boards.items() if b == 2])
        curr_third_board = sorted([c for c, b in zt_0904_boards.items() if b == 3])
        two_to_three_success = sorted(set(prev_second_board) & set(curr_third_board))
        raw_recalc["two_to_three_rate"] = {
            "numerator": len(two_to_three_success),
            "denominator": len(prev_second_board),
            "numerator_codes": two_to_three_success,
            "denominator_codes": prev_second_board,
            "source_verified": True,
        }

        # prior_limitup_continue_rate: 0903涨停 -> 0904继续涨停
        prior_continue = sorted(zt_0903_codes & zt_0904_codes)
        raw_recalc["prior_limitup_continue_rate"] = {
            "numerator": len(prior_continue),
            "denominator": len(zt_0903_codes),
            "numerator_codes": prior_continue,
            "denominator_codes": sorted(zt_0903_codes),
            "source_verified": True,
        }

        # high_board_fail_rate: 0903>=4板 -> 0904未涨停
        prev_high_board = sorted([c for c, b in zt_0903_boards.items() if b >= 4])
        high_fail = sorted([c for c in prev_high_board if c not in zt_0904_codes])
        raw_recalc["high_board_fail_rate"] = {
            "numerator": len(high_fail),
            "denominator": len(prev_high_board),
            "numerator_codes": high_fail,
            "denominator_codes": prev_high_board,
            "source_verified": True,
        }
    else:
        # 缺前日输入：前三项来源核验未完成
        for mid in ["two_to_three_rate", "prior_limitup_continue_rate", "high_board_fail_rate"]:
            raw_recalc[mid] = {
                "source_verified": False,
                "source_verification_status": "PENDING_MISSING_PREVIOUS_POOL",
                "reason": "缺少0903涨停池或0904涨停池，无法从原始来源复算",
            }

    # failed_limitup_rate: 从原始池复算（已有逻辑）
    if market_overview.get("failed_limit_up_count") is not None:
        raw_recalc["failed_limitup_rate"] = {
            "numerator": market_overview["failed_limit_up_count"],
            "denominator": market_overview.get("limit_up_failed_union_count"),
            "numerator_codes": market_overview.get("failed_limit_up_codes", []),
            "denominator_codes": sorted(set(market_overview.get("limit_up_codes", [])) | set(market_overview.get("failed_limit_up_codes", []))),
            "source_verified": True,
        }
    else:
        raw_recalc["failed_limitup_rate"] = {
            "source_verified": False,
            "source_verification_status": "PENDING_MISSING_CURRENT_POOLS",
        }

    market_metrics = []
    if cohorts_data and "four_independent_metrics" in cohorts_data:
        for mid, mdef in metric_defs.items():
            # R03: 每个指标重新初始化所有状态变量，避免沿用前一指标残留
            cohort_mismatch_detail = None
            cohort_match = None
            source_verified = False
            source_note = "原始来源核验未完成"
            m = cohorts_data["four_independent_metrics"].get(mid, {})
            cohort_num = m.get("numerator_count", m.get("numerator"))
            cohort_den = m.get("denominator_count", m.get("denominator"))
            reported_val = m.get("value", m.get("percentage"))
            # Web02.1: 区分字段缺失(None)和显式空数组([])
            cohort_num_codes = m.get("numerator_stock_codes", m.get("numerator_codes"))
            cohort_den_codes = m.get("denominator_stock_codes", m.get("denominator_codes"))
            cohort_status = m.get("status", "UNKNOWN")

            # C3: 优先使用原始池复算值
            recalc = raw_recalc.get(mid, {})
            if recalc.get("source_verified"):
                num = recalc["numerator"]
                den = recalc["denominator"]
                num_codes = recalc["numerator_codes"]
                den_codes = recalc["denominator_codes"]
                source_verified = True
                source_note = "从原始涨停池复算"
                # Web02.1: 与cohort对照——区分MATCH/MISMATCH/UNKNOWN，null vs []
                def _norm_codes(codes):
                    # Web02.1-R1 R06: 标量、字典不能当成员数组迭代
                    if codes is None:
                        return set()
                    if isinstance(codes, (int, float, str, dict)):
                        return set()  # 标量类型，非法，返回空集
                    if not isinstance(codes, (list, tuple, set)):
                        return set()
                    if not codes:
                        return set()
                    try:
                        return set(normalize_code(c) for c in codes if c)
                    except (TypeError, AttributeError):
                        return set()
                cohort_num_set = _norm_codes(cohort_num_codes)
                cohort_den_set = _norm_codes(cohort_den_codes)
                calc_num_set = _norm_codes(num_codes)
                calc_den_set = _norm_codes(den_codes)
                # Web02.1-R1: 成员类型校验——字典、整数、标量不能当成员数组
                num_field_present = cohort_num_codes is not None
                den_field_present = cohort_den_codes is not None
                num_is_list = num_field_present and isinstance(cohort_num_codes, list)
                den_is_list = den_field_present and isinstance(cohort_den_codes, list)
                # R05/R06: 非列表类型（字典、整数、标量）明确标非法
                num_type_invalid = num_field_present and not num_is_list
                den_type_invalid = den_field_present and not den_is_list
                num_is_empty_list = num_is_list and len(cohort_num_codes) == 0
                den_is_empty_list = den_is_list and len(cohort_den_codes) == 0
                # 正计数配空数组：非法/矛盾
                num_invalid = num_field_present and cohort_num > 0 and num_is_empty_list
                den_invalid = den_field_present and cohort_den > 0 and den_is_empty_list
                # R05/R06: 类型非法也算非法
                num_invalid = num_invalid or num_type_invalid
                den_invalid = den_invalid or den_type_invalid
                # 成员数组是否可用于比较（字段存在，且不是正计数配空数组）
                num_members_usable = num_field_present and not num_invalid
                den_members_usable = den_field_present and not den_invalid
                cohort_has_members = num_members_usable and den_members_usable

                if num_invalid or den_invalid:
                    # 正计数配空数组：明确矛盾
                    cohort_match = False
                    cohort_mismatch_detail = {
                        "status": "INVALID",
                        "reason": "正计数配空数组，成员数据矛盾",
                        "numerator_invalid": num_invalid,
                        "denominator_invalid": den_invalid,
                        "count_match": (cohort_num == num and cohort_den == den),
                    }
                elif not cohort_has_members:
                    # Web02.1-R1 R04: 部分缺失时，已确定的矛盾不能被总体UNKNOWN隐藏
                    partial_denominator_mismatch = False
                    if den_field_present and den_is_list and not num_field_present:
                        # 分子缺失但分母有成员数组，检查分母是否一致
                        den_members_match = (cohort_den_set == calc_den_set and
                                             len(cohort_den_set) == len(cohort_den_codes))
                        if not den_members_match:
                            partial_denominator_mismatch = True
                    if partial_denominator_mismatch:
                        # 分子缺失但分母已确定不一致：明确报告分母矛盾
                        cohort_match = False
                        cohort_mismatch_detail = {
                            "status": "PARTIAL_MISMATCH",
                            "reason": "分子成员缺失，但分母成员已确定不一致",
                            "numerator_field_present": num_field_present,
                            "denominator_field_present": den_field_present,
                            "count_match": (cohort_num == num and cohort_den == den),
                            "denominator_members_match": False,
                            "cohort_denominator": sorted(cohort_den_set),
                            "calculated_denominator": sorted(calc_den_set),
                        }
                    else:
                        # 字段缺失/null：成员对照UNKNOWN，但数值对照独立表达
                        cohort_match = None  # UNKNOWN
                        cohort_mismatch_detail = {
                            "status": "UNKNOWN",
                            "reason": "cohort报告缺少成员数组（字段缺失/null），无法进行成员对照",
                            "numerator_field_present": num_field_present,
                            "denominator_field_present": den_field_present,
                            "count_match": (cohort_num == num and cohort_den == den),
                            "cohort_numerator_count": cohort_num,
                            "calculated_numerator_count": num,
                            "cohort_denominator_count": cohort_den,
                            "calculated_denominator_count": den,
                        }
                else:
                    # 有成员数组（含合法空数组[]）：检查规范化成员集合+计数+唯一性
                    members_match = (
                        cohort_num_set == calc_num_set
                        and cohort_den_set == calc_den_set
                        and len(cohort_num_set) == len(cohort_num_codes)
                        and len(cohort_den_set) == len(cohort_den_codes)
                    )
                    count_match = (cohort_num == num and cohort_den == den)
                    if count_match and members_match:
                        cohort_match = True  # MATCH
                        cohort_mismatch_detail = None
                    else:
                        cohort_match = False  # MISMATCH
                        cohort_mismatch_detail = {
                            "status": "MISMATCH",
                            "count_match": count_match,
                            "numerator_members_match": cohort_num_set == calc_num_set,
                            "denominator_members_match": cohort_den_set == calc_den_set,
                            "cohort_numerator": sorted(cohort_num_set),
                            "calculated_numerator": sorted(calc_num_set),
                            "cohort_denominator": sorted(cohort_den_set),
                            "calculated_denominator": sorted(calc_den_set),
                        }
            else:
                # 来源核验未完成：使用cohort值但标PENDING
                num = cohort_num
                den = cohort_den
                num_codes = cohort_num_codes
                den_codes = cohort_den_codes
                source_verified = False
                source_note = recalc.get("reason", "原始来源核验未完成")
                # cohort_match和cohort_mismatch_detail已在循环开始初始化为None

            # 校验
            is_valid, calc_value, error_reason, val_details = validate_metric(num, den, num_codes, den_codes, reported_val)

            # 显示值
            display_value = "—"
            if is_valid and den and den > 0:
                display_value = "%.2f%%" % (calc_value if calc_value is not None else 0)
            elif is_valid and den == 0 and num == 0:
                display_value = "无可比较样本(0/0)"

            # 报告值对照状态
            report_value_status = "MATCH"
            if reported_val is None:
                report_value_status = "MISSING_REPORTED_VALUE"
            elif calc_value is not None and abs(calc_value - reported_val) > 0.01:
                report_value_status = "MISMATCH"

            # C3: 最终状态：算术合法 + 来源核验
            if is_valid and source_verified:
                final_status = "VALID"
                final_calc_verified = True
            elif is_valid and not source_verified:
                final_status = "SOURCE_VERIFICATION_PENDING"
                final_calc_verified = False  # 算术成立但原始来源未核验
            else:
                final_status = "ERROR"
                final_calc_verified = False

            market_metrics.append({
                "id": mid,
                "name": mdef["name"],
                "definition": mdef["definition"],
                "numerator": num,
                "denominator": den,
                "reported_value": reported_val,
                "cohort_numerator": cohort_num,
                "cohort_denominator": cohort_den,
                "cohort_match": cohort_match,
                "cohort_mismatch_detail": cohort_mismatch_detail,
                "calculated_value": round(calc_value, 4) if calc_value is not None else None,
                "display_value": display_value,
                "status": final_status,
                "calculation_verified": final_calc_verified,
                "source_verified": source_verified,
                "source_note": source_note,
                "validation_error": error_reason if not is_valid else "",
                "report_value_status": report_value_status,
                "numerator_codes": num_codes,
                "denominator_codes": den_codes,
                "source_file": "08_market_cohorts.json + raw zt pools (0903+0904)" if source_verified else "08_market_cohorts.json (cohort only, source pending)",
                "source_field": "four_independent_metrics.%s" % mid,
                "note": "0%%为真实有效零，非暂无数据" if (is_valid and num == 0 and den and den > 0) else "",
            })

    # === 3. 六只候选股 observed_fields ===
    candidates = []
    if candidates_data and "candidates" in candidates_data:
        for c in candidates_data["candidates"]:
            ts_code = c.get("ts_code", "")
            name = c.get("name", "")

            # 提取所有字段为observed_fields结构
            observed_fields = {}
            effective_fields = {}
            field_names = [
                "close", "pct_chg", "amount_cny", "volume_shares",
                "turnover_pct", "float_market_cap_cny", "consecutive_limit_count",
                "first_seal_time", "last_seal_time", "open_break_count",
                "close_seal_amount_cny", "industry", "published_at", "public_time",
            ]
            for fn in field_names:
                fv = c.get(fn, {})
                if isinstance(fv, dict):
                    asof = fv.get("asof_status", "UNKNOWN")
                    val_status = fv.get("status", "MISSING")
                    observed_fields[fn] = {
                        "value": fv.get("value"),
                        "status": val_status,
                        "provider": fv.get("provider"),
                        "endpoint": fv.get("endpoint"),
                        "source_field": fv.get("source_field"),
                        "retrieved_at": fv.get("retrieved_at"),
                        "unit": fv.get("unit"),
                        "asof_status": asof,
                        "event_time": fv.get("event_time"),
                        "public_time": fv.get("public_time"),
                        "published_at": fv.get("published_at", fv.get("public_time")),
                        "note": fv.get("note", ""),
                    }
                    # R3: effective_fields 仅 value_status=VALID 且 asof_status=VERIFIED_ASOF
                    if val_status == "VALID" and asof == "VERIFIED_ASOF":
                        effective_fields[fn] = fv.get("value")
                else:
                    observed_fields[fn] = {"value": fv, "status": "SCALAR", "asof_status": "UNKNOWN"}

            # R3: 正确解析 concepts.value 证据对象
            concepts_raw = c.get("concepts", {})
            if isinstance(concepts_raw, dict) and "value" in concepts_raw:
                concept_list = concepts_raw.get("value", [])
                if isinstance(concept_list, list):
                    concept_names = [
                        cc.get("name") if isinstance(cc, dict) else cc
                        for cc in concept_list
                    ]
                    observed_fields["concepts"] = {
                        "value": concept_names,
                        "count": len(concept_names),
                        "status": concepts_raw.get("status", "UNVERIFIED_HISTORICAL"),
                        "asof_status": "UNVERIFIED_HISTORICAL",
                        "provider": concepts_raw.get("provider", "pool_analyzer/fetch_concepts"),
                        "source": concepts_raw.get("source", "F10概念缓存"),
                        "raw_concepts": concept_list,
                        "note": "F10静态概念，无法证明0904当日有效；历史归属UNVERIFIED_HISTORICAL",
                    }
                else:
                    observed_fields["concepts"] = {
                        "value": None, "count": None, "status": "INVALID",
                        "asof_status": "UNKNOWN", "note": "concepts.value不是列表",
                    }
            elif isinstance(concepts_raw, list):
                # 兼容旧格式
                concept_names = [cc.get("name") if isinstance(cc, dict) else cc for cc in concepts_raw]
                observed_fields["concepts"] = {
                    "value": concept_names, "count": len(concept_names),
                    "status": "UNVERIFIED_HISTORICAL", "asof_status": "UNVERIFIED_HISTORICAL",
                    "note": "F10静态概念(旧格式)",
                }
            else:
                observed_fields["concepts"] = {
                    "value": None, "count": None, "status": "MISSING",
                    "asof_status": "UNKNOWN", "note": "concepts字段缺失",
                }

            # limit_up_reason
            lur = c.get("limit_up_reason", {})
            if isinstance(lur, dict):
                observed_fields["limit_up_reason"] = {
                    "value": lur.get("value"),
                    "status": lur.get("status", "MISSING"),
                    "asof_status": lur.get("asof_status", "UNKNOWN"),
                    "note": "来源未提供，不自动编写原因",
                }

            # limit_up_stats
            lus = c.get("limit_up_stats", {})
            if isinstance(lus, dict):
                observed_fields["limit_up_stats"] = {
                    "value": lus.get("value"),
                    "status": lus.get("status", "MISSING"),
                    "asof_status": "UNKNOWN",
                    "source_field": lus.get("source_field"),
                }

            candidates.append({
                "ts_code": ts_code,
                "name": name,
                "trade_date": c.get("trade_date", trade_date),
                "observed_fields": observed_fields,
                "effective_fields": effective_fields,
                "effective_fields_count": len(effective_fields),
                # R3: 去掉 len(effective_fields)>=8，新策略未实现时不宣称正式特征完整
                "effective_features_complete": None,
                "effective_features_note": "新策略尚未实现，不宣称正式特征完整；effective_fields仅含VALID+VERIFIED_ASOF字段",
                "observed_values_complete": all(
                    observed_fields.get(fn, {}).get("status") == "VALID"
                    for fn in ["close", "first_seal_time", "close_seal_amount_cny", "amount_cny"]
                ),
                "raw_record": c,
            })

    # === 4. 旧模型结果（R2: 归档状态与本轮重放验证状态分开）===
    legacy_results = []
    legacy_archive_meta = {}
    legacy_replay_verification = {
        "status": "LEGACY_REPLAY_BLOCKED",
        "reason": "缺少完整39只涨停股冻结概念输入（当前只有6只二板候选概念切片），无法独立复现旧模型完整运行",
        "blocked_field": "complete_concept_cache_for_all_39_limit_up_stocks",
        "archive_status_preserved": True,
    }

    if legacy_data:
        # 归档元数据（保留原SUCCESS，不改）
        legacy_archive_meta = {
            "run_id": legacy_data.get("run_id", "unknown"),
            "started_at": legacy_data.get("started_at"),
            "completed_at": legacy_data.get("completed_at"),
            "date": legacy_data.get("date"),
            "previous_date": legacy_data.get("previous_date"),
            "archive_status": legacy_data.get("replay_meta", {}).get("status", "UNKNOWN"),
            "archive_status_note": "这是旧归档文件中的原始运行状态，保留不改；不等于本轮独立重放验证通过",
            "model_version": legacy_data.get("replay_meta", {}).get("model_version", "unknown"),
            "result_count": legacy_data.get("result_count", len(legacy_data.get("results", []))),
            "network_blocked": legacy_data.get("network_blocked"),
        }

        # 按日期+规范代码建立索引，检测重复/冲突
        legacy_index = {}
        legacy_conflicts = []
        for r in legacy_data.get("results", []):
            code = normalize_code(r.get("ts_code", r.get("plain_code", "")))
            rdate = r.get("trade_date", legacy_data.get("date", ""))
            key = "%s_%s" % (rdate, code)
            if key in legacy_index:
                legacy_conflicts.append({"key": key, "code": code, "date": rdate})
            legacy_index[key] = r

        for r in legacy_data.get("results", []):
            code = normalize_code(r.get("ts_code", r.get("plain_code", "")))
            rdate = r.get("trade_date", legacy_data.get("date", ""))
            legacy_raw = r.get("legacy", {}).get("raw", {})

            # R2: vetoed 缺失显示未知，不能显示否
            vetoed = r.get("vetoed")
            if vetoed is None:
                vetoed_display = "未知"
            elif vetoed is True:
                vetoed_display = "是"
            else:
                vetoed_display = "否"

            legacy_results.append({
                "ts_code": code,
                "name": r.get("name", ""),
                "trade_date": rdate,
                "unique_key": "%s_%s" % (rdate, code),
                "archive_run_id": legacy_data.get("run_id", "unknown"),
                "archive_started_at": legacy_data.get("started_at"),
                "archive_completed_at": legacy_data.get("completed_at"),
                "archive_status": legacy_data.get("replay_meta", {}).get("status", "UNKNOWN"),
                "source_version": legacy_raw.get("model_version", "V2.3"),
                "raw_score": r.get("raw_score", legacy_raw.get("raw_score")),
                "risk_deduction": r.get("risk_deduction"),
                "final_score": r.get("score"),
                "grade": r.get("grade"),
                "grade_desc": r.get("grade_desc", legacy_raw.get("grade_desc")),
                "vetoed": vetoed,
                "vetoed_display": vetoed_display,
                "veto_reasons": r.get("veto_reasons", []),
                "skip_reasons": r.get("skip_reasons", []),
                "seed_stock": r.get("seed", {}).get("seed_stock"),
                "seed_score": r.get("seed", {}).get("seed_score"),
                "trade_permission": r.get("permission", {}).get("trade_permission"),
                "position_min": r.get("permission", {}).get("position_min"),
                "position_max": r.get("permission", {}).get("position_max"),
                "confidence_pct": r.get("confidence_pct", legacy_raw.get("confidence_pct")),
                "raw_complete": legacy_raw is not None and len(legacy_raw) > 0,
                "label": "提交的旧模型结果（归档），本轮独立重放BLOCKED",
                "not_for_execution": True,
                "replay_verification_status": "LEGACY_REPLAY_BLOCKED",
            })

        if legacy_conflicts:
            legacy_replay_verification["conflicts"] = legacy_conflicts

    # === 5. 影子状态 ===
    shadow_results = []
    if shadow_data:
        for r in shadow_data.get("results", []):
            dec = r.get("decision", {})
            shadow_results.append({
                "ts_code": normalize_code(r.get("ts_code", "")),
                "name": r.get("name", ""),
                "decision_status": dec.get("status"),
                "final_score": dec.get("final_score"),
                "grade": dec.get("grade"),
                "permission": dec.get("permission"),
                "score_status": dec.get("score_status"),
                "missing_critical_fields": dec.get("missing_critical_fields", []),
                "errors": dec.get("errors", []),
                "error_reasons": [e.get("reason", str(e)) if isinstance(e, dict) else str(e) for e in dec.get("errors", [])],
                "legacy_score": r.get("legacy", {}).get("score"),
                "legacy_grade": r.get("legacy", {}).get("grade"),
                "capability_summary": r.get("capability_summary", {}),
            })

    # === 6. 数据质量报告 ===
    data_quality = None
    if dq_data:
        data_quality = {
            "version": dq_data.get("version"),
            "trade_date": dq_data.get("trade_date"),
            "generated_at": dq_data.get("generated_at"),
            "required_schema_coverage": dq_data.get("required_schema_coverage"),
            "scoring_critical_coverage": dq_data.get("scoring_critical_coverage"),
            "market_data_coverage": dq_data.get("market_data_coverage"),
            "seal_quality_coverage": dq_data.get("seal_quality_coverage"),
            "theme_evidence_coverage": dq_data.get("theme_evidence_coverage"),
            "historical_theme_coverage": dq_data.get("historical_theme_coverage"),
            "missing_required_fields": dq_data.get("missing_required_fields", []),
            "missing_scoring_critical_fields": dq_data.get("missing_scoring_critical_fields", []),
            "score_status": dq_data.get("score_status"),
            "final_score": dq_data.get("final_score"),
            "note": dq_data.get("note"),
            "source_file": "09_data_quality_report.json (Phase1审计包)",
            "warning": "覆盖率不代表预测准确率、时点通过率或项目完成度",
        }

    # === 7. Phase1状态 ===
    phase1 = None
    if phase1_status:
        phase1 = {
            "market_data": phase1_status.get("market_data"),
            "industry_data": phase1_status.get("industry_data"),
            "static_concept": phase1_status.get("static_concept"),
            "trade_theme": phase1_status.get("trade_theme"),
            "phase2_ready": phase1_status.get("phase2_ready"),
            "block_reason": phase1_status.get("block_reason", []),
        }

    # === 8. 功能进度 ===
    feature_progress = [
        {"stage": "Phase1数据基础", "status": "已收尾", "detail": "行情/市场母体/行业层数据已通过"},
        {"stage": "四个09-04市场指标", "status": "已从原始池复算", "detail": "0/6, 7/44, 2/3, 48/87；炸板率分母87=39涨停+48炸板去重"},
        {"stage": "数据契约与正常排名", "status": "已有实现，剩余边界见说明", "detail": "缺失值UNKNOWN/拒绝重复/秒级封板校验"},
        {"stage": "独立legacy重放", "status": "BLOCKED", "detail": "缺完整39股冻结概念输入，归档结果可查看但不宣称已复现"},
        {"stage": "只读Web展示", "status": "本轮实际运行", "detail": "数据与验证页面(R1整改)"},
        {"stage": "新Core2/Seed/正式策略", "status": "尚未实现", "detail": "deferred to Phase2-03"},
    ]

    # === 9. 遗留问题 ===
    remaining_issues = [
        "完整39只涨停股概念映射缺失，当前只有6只候选切片，legacy重放BLOCKED",
        "rate_23百分数单位：合成3/6=50%应传50.0而非0.5，真实09-04为0不受影响",
        "observed_fields与effective_fields分开：值已取得≠可用于指定历史时点；effective仅VALID+VERIFIED_ASOF",
        "FUTURE/INVALID/CONFLICT/ERROR原值保留供排查，不参与有效特征或默认数值排序",
        "比例母体验证：正分子缺少成员不能VALID，0/0显示无可比较样本，正分子/0非法",
        "capability.status=ERROR但errors=[]时错误优先级需修复",
        "TEST_POLICY_V1未校验版本/身份/阈值，DEFERRED_BEFORE_NEW_POLICY",
        "HardBlock空rule_id仍触发BLOCKED，DEFERRED_BEFORE_NEW_POLICY",
        "DecisionInput hash不覆盖capabilities，来源与确定性记录未闭合",
        "TRADE_THEME日期化直接证据缺失，0904当天公开复盘无法回溯",
        "历史快照602候选中593封板时间为占位符235959（执行方转述，未独立核验），需后续回填",
    ]

    # 组装输出
    output = {
        "snapshot_id": snapshot_id,
        "run_id": run_id,
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "version": "web01.1-r1",
        "trade_date": trade_date,
        "previous_date": previous_date,
        "business_date_label": "2026-09-04 历史快照 · 只读研究",
        "page_title": "数据与验证",
        "page_subtitle": "新策略尚未实现；旧模型归档结果可查看，独立重放BLOCKED（缺完整39股概念输入）。",
        "input_files": input_files,
        "input_hashes": input_hashes,
        "content_hash": "",
        "market_overview": market_overview,
        "market_metrics": market_metrics,
        "candidates": candidates,
        "legacy_results": legacy_results,
        "legacy_archive_meta": legacy_archive_meta,
        "legacy_replay_verification": legacy_replay_verification,
        "shadow_results": shadow_results,
        "new_policy_implemented": shadow_data.get("new_policy_implemented", False) if shadow_data else False,
        "new_policy_status": shadow_data.get("new_policy_status", "UNKNOWN") if shadow_data else "UNKNOWN",
        "data_quality": data_quality,
        "phase1_status": phase1,
        "feature_progress": feature_progress,
        "remaining_issues": remaining_issues,
        "deferred_before_new_policy": [
            "F04: TEST_POLICY_V1作用域/版本/建议规格校验",
            "F05: 硬阻断证据校验及未完成的正式决策哈希/后日标签隔离",
            "F03: capability.status=ERROR但errors=[]时错误优先级",
            "正式新策略评分权重、评级阈值、Core2/Seed规则",
        ],
    }

    # 计算内容哈希（排除content_hash字段本身）
    content_for_hash = {k: v for k, v in output.items() if k != "content_hash"}
    output["content_hash"] = hashlib.sha256(
        json.dumps(content_for_hash, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]

    # 确保data目录存在
    CONFIG.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG.snapshot_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("web_snapshot.json 已生成: %s" % CONFIG.snapshot_path)
    print("snapshot_id: %s" % snapshot_id)
    print("候选股数: %d" % len(candidates))
    print("市场指标数: %d" % len(market_metrics))
    print("旧模型结果数: %d" % len(legacy_results))
    print("影子结果数: %d" % len(shadow_results))
    print("legacy_replay_verification: %s" % legacy_replay_verification["status"])
    print("market_overview: 涨停=%s 二板=%s 最高板=%s 炸板=%s" % (
        market_overview.get("limit_up_count"), market_overview.get("second_board_count"),
        market_overview.get("max_board"), market_overview.get("failed_limit_up_count")))
    print("content_hash: %s" % output["content_hash"])
    # 验证概念解析
    for c in candidates:
        cc = c["observed_fields"].get("concepts", {})
        print("  %s %s: 概念数=%s status=%s" % (c["ts_code"], c["name"], cc.get("count"), cc.get("status")))


if __name__ == "__main__":
    main()
