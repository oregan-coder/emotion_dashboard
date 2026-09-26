# -*- coding: utf-8 -*-
"""
03B-01-R1 证据台账模块（重写版）

修复G1-G3：
- G1: 索引范围与来源角色
- G2: 统一校验与隔离流程
- G3: CLI/API/页面错误与证据展示

契约版本: 03b01.v1
固定参数: trade_date=20260904, time_scope=T_CLOSE, decision_cutoff=2026-09-04T15:00:00+08:00
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ============================================================
# 固定参数
# ============================================================

SCHEMA_VERSION = "03b01.v1"
FIXED_TRADE_DATE = "20260904"
FIXED_TIME_SCOPE = "T_CLOSE"
FIXED_DECISION_CUTOFF = "2026-09-04T15:00:00+08:00"

# 允许索引的顶层目录（按相对路径包含关系判断）
ALLOWED_TOP_DIRS = ["data", "reference_inputs", "references", "research_evidence"]

# 排除的目录名（运行期测试、临时合成）
EXCLUDED_DIR_NAMES = {"tests", "__pycache__", ".pytest_cache", "node_modules"}

# 排除的文件扩展名（代码、旧ZIP、运行截图）
EXCLUDED_EXTENSIONS = {
    ".py", ".pyc", ".pyo", ".pyd",  # 代码
    ".zip", ".tar", ".gz", ".rar", ".7z",  # 压缩包
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg",  # 图片/截图
    ".exe", ".dll", ".so", ".dylib",  # 二进制
    ".bat", ".cmd", ".sh", ".ps1", ".vbs",  # 脚本
    ".log",  # 日志
}

# 证据种类枚举
VALID_EVIDENCE_KINDS = {"DIRECT_CLAIM", "STATIC_CLUE", "CONTEXT_OBSERVATION", "METHOD_REFERENCE"}

# 极性枚举
VALID_POLARITIES = {"SUPPORTS", "CONTRADICTS", "CONTEXT"}

# 成员范围枚举
VALID_MEMBER_SCOPES = {"UNKNOWN", "SINGLE", "PARTIAL", "DECLARED_COMPLETE"}

# 时间精度枚举
VALID_TIME_PRECISIONS = {"TIMESTAMP", "DATE"}

# 来源角色（非直接证据角色）
NON_DIRECT_ROLES = {"METHOD_REFERENCE", "STATIC_CLUE", "ARCHIVED_RESULT", "LEGACY_CONTEXT", "QUALITY_REPORT"}


# ============================================================
# 异常类
# ============================================================

class LedgerRootError(ValueError):
    """根级输入错误（文件缺失、坏JSON、根日期/scope/cutoff不符）"""
    def __init__(self, error_type, error_message):
        self.error_type = error_type
        self.error_message = error_message
        super().__init__(error_message)


class LedgerOutputError(Exception):
    """输出路径错误（output与input相同、覆盖原件）"""
    def __init__(self, error_type, error_message):
        self.error_type = error_type
        self.error_message = error_message
        super().__init__(error_message)


# ============================================================
# 工具函数
# ============================================================

def sha256_file(filepath):
    """计算文件SHA256"""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def parse_iso_datetime(value):
    """
    解析带时区的ISO时刻字符串。
    返回datetime对象（带时区），失败返回None。
    支持: 2026-09-04T15:00:00+08:00, 2026-09-04T07:00:00Z
    """
    if not isinstance(value, str):
        return None
    try:
        # 处理Z后缀
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            return None
        return dt
    except (ValueError, TypeError):
        return None


def normalize_cutoff(value):
    """
    规范化cutoff为带时区的datetime。
    接受等价UTC表示。
    """
    dt = parse_iso_datetime(value)
    if dt is None:
        return None
    # 转换为UTC比较
    return dt.astimezone(timezone.utc)


def is_same_instant(value1, value2):
    """判断两个ISO时刻是否为同一瞬间（接受等价UTC表示）"""
    dt1 = normalize_cutoff(value1)
    dt2 = normalize_cutoff(value2)
    if dt1 is None or dt2 is None:
        return False
    return dt1 == dt2


# ============================================================
# G1: 文件索引与来源角色
# ============================================================

def load_role_mapping(project_root):
    """
    加载planning_source_inventory.json的基线角色映射。
    返回 {relative_path: role} 字典。
    文件不存在返回空字典。
    """
    role_map = {}
    inventory_path = Path(project_root) / "research_evidence" / "planning_source_inventory.json"
    if inventory_path.exists():
        try:
            with open(inventory_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for src in data.get("sources", []):
                rel_path = src.get("relative_path")
                role = src.get("role", "UNCLASSIFIED_DOCUMENT")
                if rel_path:
                    role_map[rel_path] = role
        except (json.JSONDecodeError, OSError):
            pass
    return role_map


def is_allowed_path(rel_path):
    """
    按相对路径的真实目录包含关系判断是否允许索引。
    支持research_evidence/sources（不只是research_evidence顶层）。
    """
    parts = Path(rel_path).parts
    if not parts:
        return False
    top_dir = parts[0]
    if top_dir not in ALLOWED_TOP_DIRS:
        return False
    # research_evidence目录下只索引sources/子目录，不索引根目录下的文件（records.json等）
    if top_dir == 'research_evidence':
        if len(parts) < 3 or parts[1] != 'sources':
            return False
    # 检查是否在排除的子目录中
    for part in parts[:-1]:  # 目录部分（不含文件名）
        if part in EXCLUDED_DIR_NAMES:
            return False
    # 检查文件扩展名
    ext = Path(rel_path).suffix.lower()
    if ext in EXCLUDED_EXTENSIONS:
        return False
    return True


def build_source_catalog(project_root, inventory=None):
    """
    构建文件索引。
    按允许目录扫描，排除代码/ZIP/截图/tests。
    接入planning_source_inventory角色映射。
    inventory: 可选的planning_source_inventory.json内容（字典），如果提供则优先使用
    """
    project_root = Path(project_root).resolve()
    if inventory is not None and isinstance(inventory, dict):
        role_map = {}
        for src in inventory.get("sources", []):
            rel_path = src.get("relative_path")
            role = src.get("role", "UNCLASSIFIED_DOCUMENT")
            if rel_path:
                role_map[rel_path] = role
    else:
        role_map = load_role_mapping(project_root)
    sources = []

    for top_dir in ALLOWED_TOP_DIRS:
        top_path = project_root / top_dir
        if not top_path.exists():
            continue
        for root, dirs, files in os.walk(top_path):
            # 排除目录
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIR_NAMES]
            for fname in files:
                fpath = Path(root) / fname
                rel_path = str(fpath.relative_to(project_root)).replace("\\", "/")
                if not is_allowed_path(rel_path):
                    continue
                try:
                    file_size = fpath.stat().st_size
                    file_hash = sha256_file(fpath)
                except OSError:
                    continue
                role = role_map.get(rel_path, "UNCLASSIFIED_DOCUMENT")
                sources.append({
                    "source_id": f"src:{rel_path}",
                    "relative_path": rel_path,
                    "sha256": file_hash,
                    "bytes": file_size,
                    "role": role,
                    "public_time_basis": None,
                    "public_time_note": "未据此文件的文件名、mtime或抓取时间推断公开时点",
                })

    # 按relative_path排序
    sources.sort(key=lambda x: x["relative_path"])
    return {
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "project_root": str(project_root),
        "allowed_dirs": ALLOWED_TOP_DIRS,
        "excluded_extensions": sorted(list(EXCLUDED_EXTENSIONS)),
        "excluded_dir_names": sorted(list(EXCLUDED_DIR_NAMES)),
        "total_sources": len(sources),
        "sources": sources,
    }


# ============================================================
# G2: 统一校验与隔离流程
# ============================================================

def validate_root_structure(data):
    """
    校验根结构。
    根records必须存在且为数组；[]是合法空态。
    根坏JSON、非对象、日期/scope/cutoff不符应明确失败。
    抛出LedgerRootError。
    """
    if not isinstance(data, dict):
        raise LedgerRootError("ROOT_NOT_OBJECT", "根输入不是对象")

    # schema_version
    schema_version = data.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        raise LedgerRootError(
            "SCHEMA_VERSION_MISMATCH",
            f"schema_version={schema_version!r}，期望{SCHEMA_VERSION!r}"
        )

    # trade_date
    trade_date = data.get("trade_date")
    if trade_date != FIXED_TRADE_DATE:
        raise LedgerRootError(
            "TRADE_DATE_MISMATCH",
            f"trade_date={trade_date!r}，期望{FIXED_TRADE_DATE!r}"
        )

    # time_scope
    time_scope = data.get("time_scope")
    if time_scope != FIXED_TIME_SCOPE:
        raise LedgerRootError(
            "TIME_SCOPE_MISMATCH",
            f"time_scope={time_scope!r}，期望{FIXED_TIME_SCOPE!r}"
        )

    # decision_cutoff（接受等价UTC表示）
    decision_cutoff = data.get("decision_cutoff")
    if not is_same_instant(decision_cutoff, FIXED_DECISION_CUTOFF):
        raise LedgerRootError(
            "DECISION_CUTOFF_MISMATCH",
            f"decision_cutoff={decision_cutoff!r}，期望{FIXED_DECISION_CUTOFF!r}（等价UTC表示可接受）"
        )

    # records必须存在且为数组
    if "records" not in data:
        raise LedgerRootError("RECORDS_KEY_MISSING", "根对象缺少records键")
    if not isinstance(data["records"], list):
        raise LedgerRootError("RECORDS_NOT_ARRAY", f"records不是数组，类型={type(data['records']).__name__}")

    return True


def validate_record_fields(record):
    """
    校验单条记录的必填字段和枚举。
    返回 (is_valid, diagnostics)。
    is_valid=False时该记录应被隔离。
    """
    diagnostics = []

    # 必须是对象
    if not isinstance(record, dict):
        return False, ["RECORD_NOT_OBJECT"]

    # evidence_id
    evidence_id = record.get("evidence_id")
    if not evidence_id or not isinstance(evidence_id, str):
        diagnostics.append("MISSING_EVIDENCE_ID")

    # theme_key
    theme_key = record.get("theme_key")
    if not theme_key or not isinstance(theme_key, str):
        diagnostics.append("MISSING_THEME_KEY")

    # theme_name
    theme_name = record.get("theme_name")
    if not theme_name or not isinstance(theme_name, str):
        diagnostics.append("MISSING_THEME_NAME")

    # step: 整数1-4，排除bool
    step = record.get("step")
    if isinstance(step, bool):
        diagnostics.append("STEP_INVALID_BOOL")
    elif not isinstance(step, int) or step < 1 or step > 4:
        diagnostics.append("STEP_INVALID")

    # claim
    claim = record.get("claim")
    if not claim or not isinstance(claim, str):
        diagnostics.append("MISSING_CLAIM")

    # polarity
    polarity = record.get("polarity")
    if polarity not in VALID_POLARITIES:
        diagnostics.append(f"POLARITY_INVALID:{polarity}")

    # evidence_kind
    evidence_kind = record.get("evidence_kind")
    if evidence_kind not in VALID_EVIDENCE_KINDS:
        diagnostics.append(f"EVIDENCE_KIND_INVALID:{evidence_kind}")

    # source_id
    source_id = record.get("source_id")
    if not source_id or not isinstance(source_id, str):
        diagnostics.append("MISSING_SOURCE_ID")

    # source_sha256
    source_sha256 = record.get("source_sha256")
    if not source_sha256 or not isinstance(source_sha256, str):
        diagnostics.append("MISSING_SOURCE_SHA256")

    # source_locator
    source_locator = record.get("source_locator")
    if not source_locator or not isinstance(source_locator, str):
        diagnostics.append("MISSING_SOURCE_LOCATOR")

    # member_scope
    member_scope = record.get("member_scope")
    if member_scope not in VALID_MEMBER_SCOPES:
        diagnostics.append(f"MEMBER_SCOPE_INVALID:{member_scope}")

    # member_codes: 数组或null
    member_codes = record.get("member_codes")
    if member_codes is not None and not isinstance(member_codes, list):
        diagnostics.append("MEMBER_CODES_INVALID")

    # is_synthetic: 布尔
    is_synthetic = record.get("is_synthetic", False)
    if not isinstance(is_synthetic, bool):
        diagnostics.append("IS_SYNTHETIC_INVALID")

    # 显式time_scope检查（可省略继承根T_CLOSE）
    record_time_scope = record.get("time_scope")
    if record_time_scope is not None and record_time_scope != FIXED_TIME_SCOPE:
        diagnostics.append(f"RECORD_TIME_SCOPE_OUT_OF_SCOPE:{record_time_scope}")

    # 显式trade_date检查（可省略继承根）
    record_trade_date = record.get("trade_date")
    if record_trade_date is not None and record_trade_date != FIXED_TRADE_DATE:
        diagnostics.append(f"RECORD_TRADE_DATE_CONFLICT:{record_trade_date}")

    is_valid = len(diagnostics) == 0
    return is_valid, diagnostics


def validate_public_time(public_time):
    """
    校验public_time。
    返回 (is_valid, asof_status, time_diagnostics)。
    public_time=null是合法未知。
    错误格式/无时区→INVALID，时间UNKNOWN。
    """
    if public_time is None:
        return True, "UNKNOWN", ["PUBLIC_TIME_NULL"]

    if not isinstance(public_time, dict):
        return False, "UNKNOWN", ["PUBLIC_TIME_NOT_OBJECT"]

    precision = public_time.get("precision")
    if precision not in VALID_TIME_PRECISIONS:
        return False, "UNKNOWN", [f"PUBLIC_TIME_PRECISION_INVALID:{precision}"]

    value = public_time.get("value")
    if not isinstance(value, str):
        return False, "UNKNOWN", ["PUBLIC_TIME_VALUE_MISSING"]

    cutoff_dt = normalize_cutoff(FIXED_DECISION_CUTOFF)

    if precision == "TIMESTAMP":
        # value必须含明确UTC偏移
        dt = parse_iso_datetime(value)
        if dt is None:
            return False, "UNKNOWN", ["TIMESTAMP_MISSING_TIMEZONE_OR_INVALID"]
        # 比较
        if dt <= cutoff_dt:
            return True, "WITHIN_CUTOFF", []
        else:
            return True, "FUTURE", []

    elif precision == "DATE":
        # 日期粒度，必须有时区
        timezone_str = public_time.get("timezone")
        if not timezone_str or not isinstance(timezone_str, str):
            return False, "UNKNOWN", ["DATE_MISSING_TIMEZONE"]
        # 解析日期
        try:
            date_obj = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return False, "UNKNOWN", ["DATE_VALUE_INVALID"]
        # 解析时区
        try:
            if timezone_str.startswith("+") or timezone_str.startswith("-"):
                tz_hours = int(timezone_str[1:3])
                tz_mins = int(timezone_str[4:6]) if len(timezone_str) > 4 else 0
                tz_sign = 1 if timezone_str.startswith("+") else -1
                tz = timezone(timedelta(hours=tz_sign * tz_hours, minutes=tz_sign * tz_mins))
            else:
                return False, "UNKNOWN", ["DATE_TIMEZONE_FORMAT_INVALID"]
        except (ValueError, IndexError):
            return False, "UNKNOWN", ["DATE_TIMEZONE_PARSE_ERROR"]
        # 日期粒度转换为当地当天[00:00, 次日00:00)区间
        day_start = datetime(date_obj.year, date_obj.month, date_obj.day, 0, 0, 0, tzinfo=tz)
        day_end = day_start + timedelta(days=1)
        # 区间终点≤cutoff→WITHIN
        if day_end <= cutoff_dt:
            return True, "WITHIN_CUTOFF", []
        # 区间起点>cutoff→FUTURE
        elif day_start > cutoff_dt:
            return True, "FUTURE", []
        # 其余→UNKNOWN
        else:
            return True, "UNKNOWN", ["TIME_INTERVAL_OVERLAPS_CUTOFF"]

    return False, "UNKNOWN", ["PUBLIC_TIME_UNKNOWN_ERROR"]


def check_source_integrity(record, source_catalog):
    """
    检查引用原件的hash匹配。
    返回 (source_integrity, diagnostics)。
    """
    source_id = record.get("source_id")
    source_sha256 = record.get("source_sha256")

    if not source_id or not source_sha256:
        return "SOURCE_MISSING", ["SOURCE_ID_OR_HASH_MISSING"]

    # 在索引中查找
    found = None
    for src in source_catalog.get("sources", []):
        if src["source_id"] == source_id:
            found = src
            break

    if found is None:
        return "SOURCE_MISSING", [f"SOURCE_NOT_IN_CATALOG:{source_id}"]

    if found["sha256"] != source_sha256:
        return "HASH_MISMATCH", [f"HASH_MISMATCH:{source_id}"]

    return "HASH_MATCH", []


def check_source_role(record, source_catalog):
    """
    检查来源角色是否允许DIRECT_CLAIM。
    METHOD_REFERENCE/STATIC_CLUE/ARCHIVED_RESULT等不能作为DIRECT_CLAIM。
    返回 (is_allowed, diagnostics)。
    """
    evidence_kind = record.get("evidence_kind")
    if evidence_kind != "DIRECT_CLAIM":
        return True, []

    source_id = record.get("source_id")
    found = None
    for src in source_catalog.get("sources", []):
        if src["source_id"] == source_id:
            found = src
            break

    if found is None:
        return True, []  # SOURCE_MISSING已在其他地方处理

    role = found.get("role", "UNCLASSIFIED_DOCUMENT")
    if role in NON_DIRECT_ROLES:
        return False, [f"SOURCE_ROLE_NOT_DIRECT:{role}"]

    return True, []


def process_single_record(record, source_catalog):
    """
    处理单条记录：校验→时间→来源→角色→隔离判定。
    返回 (record_view, should_isolate, isolate_reasons)。
    """
    diagnostics = []
    should_isolate = False
    isolate_reasons = []

    # 0. 非对象记录直接隔离
    if not isinstance(record, dict):
        diagnostics.append("RECORD_NOT_OBJECT")
        should_isolate = True
        isolate_reasons.append("RECORD_NOT_OBJECT")
        record_view = {
            "evidence_id": None,
            "theme_key": None,
            "theme_name": None,
            "step": None,
            "claim": None,
            "polarity": None,
            "evidence_kind": None,
            "source_id": None,
            "source_sha256": None,
            "source_locator": None,
            "member_scope": None,
            "member_codes": None,
            "public_time": None,
            "event_time": None,
            "retrieved_at": None,
            "is_synthetic": False,
            "raw": {"_raw": record},
            "record_status": "INVALID",
            "source_integrity": "SOURCE_MISSING",
            "asof_status": "UNKNOWN",
            "time_verification": "UNVERIFIED",
            "review_status": "UNREVIEWED",
            "diagnostics": diagnostics,
            "isolate_reasons": isolate_reasons,
        }
        return record_view, should_isolate, isolate_reasons

    # 1. 字段校验
    is_valid, field_diags = validate_record_fields(record)
    diagnostics.extend(field_diags)
    if not is_valid:
        should_isolate = True
        isolate_reasons.extend(field_diags)

    # 2. is_synthetic检查
    is_synthetic = record.get("is_synthetic", False) if isinstance(record, dict) else False
    if is_synthetic:
        should_isolate = True
        isolate_reasons.append("IS_SYNTHETIC")
        diagnostics.append("IS_SYNTHETIC")

    # 3. step5或T_PLUS_1检查（OUT_OF_SCOPE）
    if isinstance(record, dict):
        step = record.get("step")
        if isinstance(step, int) and step == 5:
            should_isolate = True
            isolate_reasons.append("OUT_OF_SCOPE_STEP5")
            diagnostics.append("OUT_OF_SCOPE_STEP5")
        record_time_scope = record.get("time_scope")
        if record_time_scope == "T_PLUS_1":
            should_isolate = True
            isolate_reasons.append("OUT_OF_SCOPE_T_PLUS_1")
            diagnostics.append("OUT_OF_SCOPE_T_PLUS_1")

    # 4. public_time校验
    public_time = record.get("public_time") if isinstance(record, dict) else None
    time_valid, asof_status, time_diags = validate_public_time(public_time)
    diagnostics.extend(time_diags)
    if not time_valid:
        should_isolate = True
        isolate_reasons.extend(time_diags)
        is_valid = False  # 时间校验失败使record_status=INVALID

    # 5. 来源完整性检查
    source_integrity, source_diags = check_source_integrity(record, source_catalog)
    diagnostics.extend(source_diags)
    if source_integrity != "HASH_MATCH":
        should_isolate = True
        isolate_reasons.extend(source_diags)

    # 6. 来源角色检查（DIRECT_CLAIM时）
    role_allowed, role_diags = check_source_role(record, source_catalog)
    diagnostics.extend(role_diags)
    if not role_allowed:
        should_isolate = True
        isolate_reasons.extend(role_diags)

    # 构建记录视图
    record_view = {
        "evidence_id": record.get("evidence_id") if isinstance(record, dict) else None,
        "theme_key": record.get("theme_key") if isinstance(record, dict) else None,
        "theme_name": record.get("theme_name") if isinstance(record, dict) else None,
        "step": record.get("step") if isinstance(record, dict) else None,
        "claim": record.get("claim") if isinstance(record, dict) else None,
        "polarity": record.get("polarity") if isinstance(record, dict) else None,
        "evidence_kind": record.get("evidence_kind") if isinstance(record, dict) else None,
        "source_id": record.get("source_id") if isinstance(record, dict) else None,
        "source_sha256": record.get("source_sha256") if isinstance(record, dict) else None,
        "source_locator": record.get("source_locator") if isinstance(record, dict) else None,
        "member_scope": record.get("member_scope") if isinstance(record, dict) else None,
        "member_codes": record.get("member_codes") if isinstance(record, dict) else None,
        "public_time": public_time,
        "event_time": record.get("event_time") if isinstance(record, dict) else None,
        "retrieved_at": record.get("retrieved_at") if isinstance(record, dict) else None,
        "is_synthetic": is_synthetic,
        "raw": record if isinstance(record, dict) else {"_raw": record},
        "record_status": "SCHEMA_VALID" if is_valid else "INVALID",
        "source_integrity": source_integrity,
        "asof_status": asof_status,
        "time_verification": "UNVERIFIED",
        "review_status": "UNREVIEWED",
        "diagnostics": diagnostics,
    }

    return record_view, should_isolate, isolate_reasons


def deduplicate_and_conflict(records):
    """
    同ID去重/冲突处理。
    - 相同内容合并一次，诊断DUPLICATE_MERGED
    - 不同内容隔离整个ID组，诊断ID_CONFLICT
    返回 (merged_records, isolated_groups)。
    """
    # 按evidence_id分组
    id_groups = {}
    for rec in records:
        eid = rec.get("evidence_id") if isinstance(rec, dict) else None
        if eid not in id_groups:
            id_groups[eid] = []
        id_groups[eid].append(rec)

    merged_records = []
    isolated_groups = []

    for eid, group in id_groups.items():
        if eid is None:
            # 无ID的记录各自处理
            for rec in group:
                merged_records.append(rec)
            continue

        if len(group) == 1:
            merged_records.append(group[0])
            continue

        # 多条同ID，检查内容是否相同
        first_raw = json.dumps(group[0], sort_keys=True, ensure_ascii=False)
        all_same = all(
            json.dumps(rec, sort_keys=True, ensure_ascii=False) == first_raw
            for rec in group
        )

        if all_same:
            # 相同内容合并
            merged = dict(group[0])
            if "diagnostics" not in merged:
                merged["diagnostics"] = []
            if isinstance(merged.get("diagnostics"), list):
                merged["diagnostics"].append("DUPLICATE_MERGED")
            merged_records.append(merged)
        else:
            # 不同内容，隔离整个ID组
            for rec in group:
                rec_copy = dict(rec) if isinstance(rec, dict) else {"_raw": rec}
                if "diagnostics" not in rec_copy:
                    rec_copy["diagnostics"] = []
                if isinstance(rec_copy.get("diagnostics"), list):
                    rec_copy["diagnostics"].append("ID_CONFLICT")
                isolated_groups.append(rec_copy)

    return merged_records, isolated_groups


# ============================================================
# 主构建函数
# ============================================================

def build_ledger_view(project_root, records_path, planning_inventory_path=None):
    """
    构建台账视图。
    处理顺序：根结构校验 → 记录类型/必填/枚举/时间校验 → 来源hash与角色检查 → 同ID去重/冲突 → 统一登记或隔离出口。

    抛出LedgerRootError表示根级输入错误。
    """
    project_root = Path(project_root).resolve()
    records_path = Path(records_path)

    # 加载inventory（如果提供路径）
    inventory = None
    if planning_inventory_path is not None and Path(planning_inventory_path).exists():
        try:
            with open(planning_inventory_path, "r", encoding="utf-8") as f:
                inventory = json.load(f)
        except (json.JSONDecodeError, OSError):
            inventory = None

    # 1. 构建文件索引
    source_catalog = build_source_catalog(project_root, inventory)

    # 2. 加载records
    if not Path(records_path).exists():
        raise LedgerRootError("RECORDS_FILE_NOT_FOUND", f"records文件不存在: {records_path}")

    try:
        with open(records_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    except json.JSONDecodeError as e:
        raise LedgerRootError("RECORDS_JSON_INVALID", f"records JSON损坏: {e}")
    except OSError as e:
        raise LedgerRootError("RECORDS_READ_ERROR", f"records读取失败: {e}")

    # 3. 根结构校验
    validate_root_structure(raw_data)

    # 4. 同ID去重/冲突处理（在单条校验之前）
    raw_records = raw_data.get("records", [])
    merged_records, conflict_isolated = deduplicate_and_conflict(raw_records)

    # 5. 单条记录处理
    valid_records = []
    isolated_records = []

    for rec in merged_records:
        record_view, should_isolate, isolate_reasons = process_single_record(rec, source_catalog)
        if should_isolate:
            record_view["isolate_reasons"] = isolate_reasons
            isolated_records.append(record_view)
        else:
            valid_records.append(record_view)

    # 冲突隔离的记录也加入isolated_records
    for rec in conflict_isolated:
        record_view, should_isolate, isolate_reasons = process_single_record(rec, source_catalog)
        record_view["isolate_reasons"] = isolate_reasons + ["ID_CONFLICT"]
        if "ID_CONFLICT" not in record_view["diagnostics"]:
            record_view["diagnostics"].append("ID_CONFLICT")
        isolated_records.append(record_view)

    # 6. 统计
    summary = {
        "total_source_files": source_catalog["total_sources"],
        "registered_record_count": len(valid_records),
        "isolated_record_count": len(isolated_records),
        "confirmed_evidence_count": 0,  # 本轮全部UNREVIEWED
        "review_status": "ALL_UNREVIEWED",
    }

    # 7. 构建视图
    view = {
        "schema_version": SCHEMA_VERSION,
        "trade_date": FIXED_TRADE_DATE,
        "decision_cutoff": FIXED_DECISION_CUTOFF,
        "time_scope": FIXED_TIME_SCOPE,
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "records_input": {
            "path": str(records_path),
            "error": None,
            "root_valid": True,
        },
        "summary": summary,
        "source_catalog": source_catalog,
        "valid_records": valid_records,
        "isolated_records": isolated_records,
        "notes": [
            "当前没有确认证据，五步UNKNOWN、第五步未提供反馈等原状态保持",
            "不得为了测试演示在真实records中填写新炬网络/亚盛集团或任何主题已确认",
            "文件可读取、hash相符、时间关系可计算不表示命题为真，更不表示当日主线/周期已确认",
            "WITHIN_CUTOFF表示标注时间在研究时点前（未核验），不能写当时已证实可用",
            "FUTURE不可作为T日依据",
        ],
    }

    return view


# ============================================================
# G3: CLI入口
# ============================================================

def validate_output_path(output_path, input_path, project_root):
    """
    验证输出路径。
    - 拒绝output与input相同
    - 拒绝覆盖项目原件/冻结目录
    抛出LedgerOutputError。
    """
    output_path = Path(output_path).resolve()
    input_path = Path(input_path).resolve()
    project_root = Path(project_root).resolve()

    # 拒绝output与input相同
    if output_path == input_path:
        raise LedgerOutputError(
            "OUTPUT_EQUALS_INPUT",
            f"输出路径与输入路径相同: {output_path}"
        )

    # 拒绝覆盖项目原件（输出路径在项目根目录内且不是新生成的视图文件）
    # 允许输出到项目外或项目内的新文件
    # 但拒绝覆盖research_evidence/records.json等原件
    protected_files = [
        project_root / "research_evidence" / "records.json",
        project_root / "research_evidence" / "planning_source_inventory.json",
    ]
    for pf in protected_files:
        if output_path == pf.resolve():
            raise LedgerOutputError(
                "OUTPUT_OVERWRITES_PROTECTED_FILE",
                f"输出路径覆盖受保护文件: {output_path}"
            )

    return True


def main():
    """CLI入口"""
    parser = argparse.ArgumentParser(description="03B-01证据台账构建器")
    parser.add_argument("--project-root", required=True, help="项目根目录")
    parser.add_argument("--input", required=True, help="records.json输入路径")
    parser.add_argument("--output", required=True, help="台账视图输出路径")
    args = parser.parse_args()

    try:
        # 验证输出路径
        validate_output_path(args.output, args.input, args.project_root)

        # 构建台账视图
        view = build_ledger_view(
            project_root=args.project_root,
            records_path=args.input,
        )

        # 写入输出
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(view, f, ensure_ascii=False, indent=2)

        summary = view["summary"]
        print(f"台账视图已生成: {args.output}")
        print(f"资料文件数: {summary['total_source_files']}")
        print(f"登记记录数: {summary['registered_record_count']}")
        print(f"隔离记录数: {summary['isolated_record_count']}")
        sys.exit(0)

    except LedgerRootError as e:
        print(f"[根级错误] {e.error_type}: {e.error_message}", file=sys.stderr)
        error_obj = {
            "error": True,
            "error_type": e.error_type,
            "error_message": e.error_message,
        }
        # 尝试写入错误到输出（如果路径合法）
        try:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(error_obj, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        sys.exit(1)

    except LedgerOutputError as e:
        print(f"[输出错误] {e.error_type}: {e.error_message}", file=sys.stderr)
        sys.exit(2)

    except Exception as e:
        print(f"[内部错误] {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
