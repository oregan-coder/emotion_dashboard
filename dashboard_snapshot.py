# -*- coding: utf-8 -*-

"""
A股打板情绪仪表盘 V3.1.1

Web数据桥接模块（修复版）

作用：
保存 start.py 一次运行后的最终结果
不参与任何计算

修复内容：
1. position 是 dict，原 getattr 读取导致仓位全空 —— 改为兼容 dict/对象
2. cycle 字段名对齐 cycle_engine：
   space_cycle  -> height_cycle
   conclusion   -> comprehensive
   并补充 stage / description
3. 补充 market（市场广度）与 limit（涨停生态）
4. 补充砸盘明细：rates / high_feedback / 高位统计
5. 补充 emotion 明细 detail（情绪分构成）
6. 补充 ladder 连板梯队（从涨停池实时统计）
"""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
from input_contracts import number, integer, clean_json, normalize_code
import os
import traceback
import hashlib


DATA_FILE = (
    Path(__file__).parent
    /
    "data"
    /
    "dashboard.json"
)

# 历史快照目录（交易日回放用）
SNAPSHOT_DIR = (
    Path(__file__).parent
    /
    "data"
    /
    "dashboards"
)


# ============================================================
# 安全读取
# ============================================================

def safe_get(obj, key, default=""):
    """
    兼容 dict / 普通对象 / dataclass
    """

    if obj is None:
        return default

    if isinstance(obj, dict):
        return obj.get(key, default)

    return getattr(obj, key, default)


def safe_float(value, default=None):
    # `default` retained for signature compatibility, never imputes invalid data.
    return number(value)



def safe_int(value, default=None):
    return integer(value)



def safe_float_or_none(value):
    return number(value)



def safe_int_or_none(value):
    return integer(value)



def frame_len(value):
    """
    DataFrame / list 行数安全获取
    """

    if value is None:
        return 0

    try:
        return len(value)
    except Exception:
        return 0


# ============================================================
# 市场广度
# ============================================================

def market_breadth(market):
    if market is None or not hasattr(market, "columns") or "涨跌幅" not in market.columns:
        return {"up":None,"down":None,"flat":None,"unknown":None,"status":"DATA_PENDING"}
    vals=[number(v) for v in market["涨跌幅"]]
    known=[v for v in vals if v is not None]
    complete=len(known)==len(vals)
    return {"up":sum(v>0 for v in known) if complete else None,
            "down":sum(v<0 for v in known) if complete else None,
            "flat":sum(v==0 for v in known) if complete else None,
            "unknown":len(vals)-len(known),"status":"VALID" if complete else "DATA_PENDING"}



# ============================================================
# 涨停生态统计（含昨日对比 + 封板率）
# ============================================================

def _col_name(df, candidates):
    """模糊匹配列名"""
    if df is None or not hasattr(df, "columns"):
        return None
    for c in candidates:
        if c in df.columns:
            return c
    return None


def calc_limit_stats(limit_up, previous_limit_up, current_date=""):
    # Compatibility path without verified today quotes cannot decide whether
    # non-returned members are failures, suspended, or missing.
    return {"today_up":len(limit_up) if limit_up is not None else None,
            "prev_up":len(previous_limit_up) if previous_limit_up is not None else None,
            "seal_rate":None,"prev_down":None,"status":"COHORT_EVIDENCE_REQUIRED"}


def previous_limit_down(previous_date):
    """Read only the exact preceding trading day's saved count."""
    target = str(previous_date or "").replace("-", "")
    if len(target) != 8 or not target.isdigit():
        return None, "DATA_PENDING"
    try:
        from history_manager import load_history
        rows = load_history()
        if rows is None or rows.empty:
            return None, "DATA_PENDING"
        matched = rows[rows["date"].astype(str).str.replace("-", "", regex=False) == target]
        if matched.empty:
            return None, "DATA_PENDING"
        value = number(matched.iloc[-1].get("limit_down_count"))
        if value is None or value < 0 or int(value) != value:
            return None, "DATA_PENDING"
        return int(value), "VALID"
    except Exception:
        return None, "SOURCE_ERROR"



# ============================================================
# 连板梯队
# ============================================================

def board_ladder(limit_up):
    """
    从涨停池统计各连板高度数量

    返回：
    {1: 33, 2: 3, 3: 1, 5: 1}
    """

    counts = {}

    try:

        from three_board_model import _extract_stocks

        frame = pd.DataFrame(_extract_stocks(limit_up))

        if frame is not None and not frame.empty:

            for board, count in frame["board"].value_counts().items():

                counts[int(board)] = int(count)

    except Exception:

        pass

    return counts


# ============================================================
# 主入口
# ============================================================

def save_dashboard_snapshot(
        data,
        smash,
        emotion,
        cycle,
        position,
        archive_only=False
):
    """
    archive_only=False：写 dashboard.json（今日） + 历史快照
    archive_only=True ：只写历史快照（回填历史交易日用，不覆盖今日）
    """

    # ----------
    # 连板梯队
    # ----------

    ladder = board_ladder(
        getattr(data, "limit_up", None)
    )
    # 涨停池为空时回退引擎统计
    if not ladder:

        ladder = {
            1: safe_int(safe_get(smash, "first_board", 0)),
            2: safe_int(safe_get(smash, "second_board", 0)),
            3: safe_int(safe_get(smash, "third_board", 0)),
            4: safe_int(safe_get(smash, "fourth_board", 0)),
            5: safe_int(safe_get(smash, "fifth_board", 0)),
        }

        ladder = {
            k: v
            for k, v in ladder.items()
            if v is not None and v > 0
        }

    # ----------
    # 涨停梯队与概念（2板/1板/明日三板预案）
    # ----------

    pool = {}
    optional_errors = []

    try:

        from pool_analyzer import analyze_pool

        pool = analyze_pool(
            getattr(data, "limit_up", None),
            str(safe_get(data, "date", ""))
        )

    except Exception as exc:
        optional_errors.append({"module":"pool_analyzer","status":"ERROR","error":str(exc)})
        pool = {}

    # ----------
    # 龙头监控
    # ----------

    leader = {}

    try:

        from leader_monitor import build_leader_monitor

        leader = build_leader_monitor(
            getattr(data, "limit_up", None),
            getattr(data, "open_board", None),
            getattr(data, "previous_limit_up", None)
        )

    except Exception as exc:
        optional_errors.append({"module":"leader_monitor","status":"ERROR","error":str(exc)})
        leader = {}

    # ----------
    # 涨停生态统计（含昨日对比 + 封板率）
    # ----------

    limit_stats = calc_limit_stats(
        getattr(data, "limit_up", None),
        getattr(data, "previous_limit_up", None),
        str(safe_get(data, "date", ""))
    )
    prev_down, prev_down_status = previous_limit_down(str(safe_get(data, "previous_date", "")))

    result = {

        # =====================
        # 基本信息
        # =====================

        "date":
            str(safe_get(data, "date", "")),

        "previous_date":
            str(safe_get(data, "previous_date", "")),

        "update_time":
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),

        # =====================
        # 市场广度
        # =====================

        "market":
            market_breadth(
                getattr(data, "market", None)
            ),

        # =====================
        # 涨停生态（今日/昨日对比 + 封板率）
        # =====================

        "limit": {
            "up":
                limit_stats["today_up"],

            "prev_up":
                limit_stats["prev_up"],

            "down":
                frame_len(
                    getattr(data, "limit_down", None)
                ),

            "prev_down":
                prev_down,

            "prev_down_date":
                str(safe_get(data, "previous_date", "")),

            "prev_down_status":
                prev_down_status,

            "seal_rate":
                limit_stats["seal_rate"],
        },

        # =====================
        # 市场情绪
        # =====================

        "emotion": {

            # P03A: score可能为None（DATA_PENDING），不默认给0
            "score":
                safe_get(emotion, "score", None),

            "cycle_stage": safe_get(emotion, "cycle_stage", None),

            "height_stage": safe_get(emotion, "height_stage", None),

            "detail":
                dict(
                    safe_get(emotion, "detail", {})
                    or
                    {}
                ),

            # P03A: 数据状态和缺失字段
            "status":
                str(
                    safe_get(emotion, "status", "VALID")
                ),

            "missing_fields":
                list(
                    safe_get(emotion, "missing_fields", [])
                    or
                    []
                ),

            # P02B: BK1050昨日涨停表现（含一字）
            "bk1050":
                dict(
                    safe_get(emotion, "bk1050", {})
                    or
                    {}
                )
        },

        # =====================
        # 砸盘情绪
        # =====================

        "smash": {

            "score":
                safe_float(
                    safe_get(smash, "score", None)
                ),

            "status":
                str(
                    safe_get(smash, "status", "")
                    or
                    safe_get(smash, "state", "")
                ),

            "highest_board":
                safe_int(
                    safe_get(smash, "highest_board", None)
                ),

            "leader":
                str(
                    safe_get(smash, "highest_stock", "")
                ),

            "break_rate":
                safe_float(
                    safe_get(smash, "break_rate", None)
                ),

            "high_feedback":
                str(
                    safe_get(smash, "high_feedback", "")
                ),

            "high_count":
                safe_int(
                    safe_get(smash, "high_count", None)
                ),

            "high_continue_count":
                safe_int(
                    safe_get(smash, "high_continue_count", None)
                ),

            "high_break_count":
                safe_int(
                    safe_get(smash, "high_break_count", None)
                ),

            "rates": {
                "rate12":
                    safe_float(
                        safe_get(smash, "rate12", None)
                    ),

                "rate23":
                    safe_float(
                        safe_get(smash, "rate23", None)
                    ),

                "rate34":
                    safe_float(
                        safe_get(smash, "rate34", None)
                    ),

                "rate45":
                    safe_float(
                        safe_get(smash, "rate45", None)
                    ),

                "rate56":
                    safe_float(
                        safe_get(smash, "rate56", None)
                    ),
            }
        },

        # =====================
        # 连板梯队
        # =====================

        "ladder": [
            {
                "board": b,
                "count": c
            }
            for b, c in sorted(ladder.items())
        ],

        # =====================
        # 涨停梯队与概念
        # =====================

        "pool": {
            "second_board":
                pool.get("second_board", []),

            "first_board":
                pool.get("first_board", []),

            "tomorrow":
                _build_three_board_v2(
                    data,
                    smash,
                    str(safe_get(data, "date", "")),
                ),
        },

        # =====================
        # 龙头监控
        # =====================

        "leader": leader,

        # =====================
        # 周期判断
        # =====================

        "cycle": {

            "emotion_cycle":
                str(
                    safe_get(cycle, "emotion_cycle", "")
                ),

            "height_cycle":
                str(
                    safe_get(cycle, "height_cycle", "")
                    or
                    safe_get(cycle, "space_cycle", "")
                ),

            "comprehensive":
                str(
                    safe_get(cycle, "comprehensive", "")
                    or
                    safe_get(cycle, "conclusion", "")
                ),

            "stage":
                str(
                    safe_get(cycle, "stage", "")
                    or
                    safe_get(cycle, "comprehensive", "")
                ),

            "trend":
                str(
                    safe_get(cycle, "trend", "")
                ),

            "description":
                str(
                    safe_get(cycle, "description", "")
                ),

            "fund_cycle": safe_float_or_none(safe_get(cycle, "fund_cycle", None)),
            "fund_cycle_stage": str(safe_get(cycle, "fund_cycle_stage", "")),
            "status": str(safe_get(cycle, "status", "")),
        },

        # =====================
        # 仓位建议
        # =====================

        "position": {

            "suggest":
                str(
                    safe_get(position, "position", "")
                ),

            "risk":
                str(
                    safe_get(position, "risk", "")
                ),

            "strategy":
                str(
                    safe_get(position, "strategy", "")
                ),

            "status": str(safe_get(position, "status", "")),
            "source": str(safe_get(position, "source", "")),
            "fund_cycle": safe_float_or_none(safe_get(position, "fund_cycle", None)),
            "fund_cycle_stage": str(safe_get(position, "fund_cycle_stage", "")),
        }
    }

    context = getattr(data, "policy_context", {}) or {}
    if context:
        result["market"] = context["breadth"]
        if context.get("collection_mode") == "POOL_SCOPED_WITH_LEGU_NATIVE":
            result["market"]["display_scope_note"] = "乐咕原生口径；其他涨跌停与晋级指标仍按本地批准范围"
            result["emotion"]["breadth_source"] = "LEGULEGU"
            result["emotion"]["breadth_scope"] = "PROVIDER_NATIVE"
            result["emotion"]["input_scope_mix"] = "LEGULEGU_NATIVE_BREADTH_PLUS_APPROVED_LOCAL_EVENT_METRICS"

        result["limit"].update({"up":context["counts"]["up"],"down":context["counts"]["down"],
            "prev_up":context["continuation"]["denominator"] if context["continuation"]["status"] in ('VALID','EMPTY_EFFECTIVE') else None,
            "original_prev_up":context["continuation"]["original_count"] if context["continuation"]["status"] in ('VALID','EMPTY_EFFECTIVE') else None,
            "prev_up_status":context["continuation"]["status"],
            "observed_prior_input_rows":len((getattr(data,'policy_bundle',{}) or {}).get('previous_records',[])),
            "observed_eligible_prior_count":context["continuation"]["original_count"],
            "seal_rate":context["continuation"]["value"],"status":context["counts"]["status"]})
        result["smash"]["highest_board"] = context["highest_board"]["value"]
        result["smash"]["rates"] = {f"rate{k}{int(k)+1}":m["value"] for k,m in context["promotions"].items()}
        result["smash"]["break_rate"] = context["high_board_fail_rate"]["value"]
        result["smash"]["break_rate_semantic"] = "HIGH_BOARD_FAIL_RATE_COMPATIBILITY_ALIAS"
        result["smash"]["failed_limitup_rate"] = context["failed_limitup_rate"]["value"]
        result["emotion"]["yesterday_performance"] = context["yesterday_performance"]
        result["input_evidence"] = context
    result["three_board_runtime"] = getattr(data,"three_board_runtime",{"status":"NOT_RUN"})
    result["optional_component_errors"] = optional_errors
    result["module_status"] = getattr(data, 'module_status', {})
    result["history_write_status"] = getattr(data, 'history_write_status', {})
    result["smash"]["detail"] = dict(getattr(smash, 'smash_detail', {}) or {})
    result["smash"]["data_status"] = result["module_status"].get('smash',{}).get('status', 'VALID' if safe_get(smash,'score',None) is not None else 'DATA_PENDING')
    result["smash"]["missing_fields"] = result["smash"]["detail"].get('missing_inputs',[])
    result["smash"]["depends_on_emotion_score"] = False
    result["emotion"]["depends_on_smash_score"] = False
    result["schema_version"] = "5535-direct-repair-1"
    result["provenance"] = {"input_kind":getattr(data,"input_kind","UNCLASSIFIED"),
        "source_files":{n:hashlib.sha256((Path(__file__).parent/n).read_bytes()).hexdigest()
            for n in ("dashboard_snapshot.py","three_board_model.py","data_quality.py","approved_policy.py","market_pipeline.py")
            if (Path(__file__).parent/n).is_file()}}
    result = clean_json(result)
    def atomic_json(target, value):
        target.parent.mkdir(parents=True, exist_ok=True)
        import tempfile
        handle=tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",prefix=target.name+".",suffix=".tmp",dir=target.parent,delete=False)
        tmp=Path(handle.name)
        with handle as f:
            json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False)
            f.flush();os.fsync(f.fileno())
        os.replace(tmp,target)
    if not archive_only:
        atomic_json(DATA_FILE,result)
    # Existing snapshot history only; does not create/revive a strategy ledger.
    atomic_json(SNAPSHOT_DIR / f"{result['date']}.json", result)
    print("网页数据已保存:", DATA_FILE if not archive_only else SNAPSHOT_DIR)
    return result


# ============================================================
# 二进三决策模型 V2.0（三板预案）
# ============================================================

def _build_three_board_v2(data, smash, date: str) -> list:
    """
    使用《A股二进三决策模型 V2.0》对当日全部二板股票进行评分排序。
    仅使用截至当日收盘已确定的数据，严禁未来函数。
    """
    try:
        from three_board_model import evaluate_three_board

        limit_up = getattr(data, "limit_up", None)
        open_board = getattr(data, "open_board", None)
        previous_limit_up = getattr(data, "previous_limit_up", None)

        # V7.1: 使用safe_float_or_none/safe_int_or_none，缺失不补0
        rate_23 = safe_float_or_none(safe_get(smash, "rate23", None))
        highest_board = safe_int_or_none(safe_get(smash, "highest_board", None))

        # P03A R1: 高位晋级失败率（>=4板，smash_engine.py已使用>=4板口径）
        # smash.break_rate = high_break_count / high_count，其中high_pool = previous[board >= 4]
        # 完整母体的0有效，缺失为None，不要有效0→None
        high_board_fail_rate = safe_float(safe_get(smash, "break_rate", None))
        # 不把有效的0转为None，只把负数/无效值转为None
        if high_board_fail_rate is not None and high_board_fail_rate < 0:
            high_board_fail_rate = None

        context = getattr(data, "policy_context", {}) or {}
        prior_limitup_continue_rate = context.get("continuation", {}).get("value")
        if context:
            rate_23 = context["promotions"]["2"]["value"]
            highest_board = context["highest_board"]["value"]
            high_board_fail_rate = context["high_board_fail_rate"]["value"]

        results = evaluate_three_board(
            limit_up_df=limit_up,
            previous_limit_up_df=previous_limit_up,
            open_board_df=open_board,
            date=date,
            rate_23=rate_23,
            highest_board=highest_board,
            high_board_fail_rate=high_board_fail_rate,
            prior_limitup_continue_rate=prior_limitup_continue_rate,
            candidate_filter_evidence=getattr(data, "candidate_filter_evidence", None),
            highest_board_evidence=context.get("highest_board") if context else None,
            approved_market_evidence=context if context else None,
        )

        runtime_status = "VALID"
        if not results and (limit_up is None or not context or context.get("counts",{}).get("status") != "VALID"):
            runtime_status = "DATA_PENDING"
        elif any(r.get("input_status") != "READY" for r in results):
            runtime_status = "PARTIAL"
        setattr(data, "three_board_runtime", {"status":runtime_status, "candidate_count":len(results),
            "candidate_set_complete":bool(context) and context.get("counts",{}).get("status")=="VALID",
            "note":"调用完成不等于输入齐备；空列表仅在完整样本证明下表示无候选"})
        return results

    except Exception as e:
        error={"status":"ERROR","type":type(e).__name__,"message":str(e),"traceback":traceback.format_exc()}
        setattr(data, "three_board_runtime", error)
        # Preserve known candidate identities, not a success-looking empty pool.
        from three_board_model import _extract_stocks
        rows=_extract_stocks(getattr(data,"limit_up",None))
        return [{"code":r["code"],"name":r["name"],"close":r.get("close"),
                 "raw_score":None,"legacy_score":None,"legacy_grade":None,"rank":None,
                 "modules":{},"final_score":None,"grade":None,"permission":None,
                 "strategy_status":"NOT_ENABLED","input_status":"ERROR","score_status":"ERROR",
                 "candidate_status":"UNKNOWN","runtime_error":error,
                 "score_status_reason":"模型运行异常；保留候选，未生成完整研究分",
                 "seal_time_fmt":r.get("seal_time"),"seal_amount_fmt":"待证据","turnover":r.get("turnover")}
                for r in rows if r.get("board")==2]
