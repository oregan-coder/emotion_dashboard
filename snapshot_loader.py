# -*- coding: utf-8 -*-
"""
Phase2-Web01.1-R2: 共享快照配置、读取与校验模块
C1: 统一路径配置，复用读取/校验函数，避免复制两份加载器
C2: content_hash校验、日期校验、结构校验、重复股检测
C3: 指标原始成员来源校验
"""
import json
import hashlib
from pathlib import Path


def find_project_root(start_path=None):
    """
    Web02.1-R1: 从应用文件位置定位项目根目录，不依赖cwd。
    策略：优先从snapshot_loader.py所在目录向上查找，其次从start_path/cwd查找。
    向上查找包含 data/web_snapshot.json 或 reference_inputs/ 或 src/ 的目录。
    """
    # Web02.1-R1: 优先使用应用文件位置，确保从任意cwd启动都能找到约定文件
    candidate_roots = []
    try:
        app_file_dir = Path(__file__).resolve().parent
        candidate_roots.append(app_file_dir)
    except NameError:
        pass
    if start_path is not None:
        candidate_roots.append(Path(start_path))
    candidate_roots.append(Path.cwd())

    for start in candidate_roots:
        current = start.resolve()
        for _ in range(10):
            if (current / "data" / "web_snapshot.json").exists():
                return current
            if (current / "reference_inputs").exists():
                return current
            if (current / "src" / "validation_app.py").exists():
                return current
            parent = current.parent
            if parent == current:
                break
            current = parent

    # 兜底：返回第一个候选目录
    return candidate_roots[0].resolve() if candidate_roots else Path.cwd().resolve()


def _find_project_root_legacy(start_path=None):
    """旧版find_project_root，保留用于对比"""
    if start_path is None:
        start_path = Path.cwd()
    else:
        start_path = Path(start_path)

    current = start_path.resolve()
    for _ in range(10):  # 最多向上查找10层
        # 检查是否包含data/web_snapshot.json
        if (current / "data" / "web_snapshot.json").exists():
            return current
        # 检查是否包含reference_inputs
        if (current / "reference_inputs").exists():
            return current
        # 检查是否包含src且src下有validation_app.py
        if (current / "src" / "validation_app.py").exists():
            return current
        # 向上
        parent = current.parent
        if parent == current:
            break
        current = parent

    # 兜底：返回当前目录
    return start_path.resolve()


def normalize_code(code):
    """
    Web02.1: 统一股票代码格式。
    605398 -> 605398.SH, 002403 -> 002403.SZ, 605398.SH -> 605398.SH
    缺失或非法返回None，不默认编造身份。
    """
    if not code or not isinstance(code, str):
        return None
    code = code.strip().upper()
    if not code:
        return None
    # 已经带后缀
    if '.' in code:
        parts = code.split('.')
        # R03: 必须是6位数字 + 合法后缀
        if len(parts) == 2 and len(parts[0]) == 6 and parts[0].isdigit() and parts[1] in ('SH', 'SZ', 'BJ'):
            return code
        return None
    # 纯数字代码
    if code.isdigit() and len(code) == 6:
        if code.startswith(('6', '9')):
            return code + '.SH'
        elif code.startswith(('0', '2', '3')):
            return code + '.SZ'
        elif code.startswith(('4', '8')):
            return code + '.BJ'
    return None


def build_identity_key(trade_date, ts_code):
    """Web02.1: 用规范代码构造身份键。"""
    norm_code = normalize_code(ts_code)
    if norm_code is None:
        return None
    return "%s_%s" % (trade_date, norm_code)


class SnapshotConfig:
    """统一路径配置"""

    def __init__(self, project_root=None, snapshot_path=None, inputs_path=None):
        if project_root is None:
            project_root = find_project_root()
        self.project_root = Path(project_root)

        # 快照路径：优先显式指定，否则用包根data/
        if snapshot_path:
            self.snapshot_path = Path(snapshot_path)
        else:
            self.snapshot_path = self.project_root / "data" / "web_snapshot.json"

        # 原始输入路径：优先显式指定，否则用包根reference_inputs/
        if inputs_path:
            self.inputs_path = Path(inputs_path)
        else:
            self.inputs_path = self.project_root / "reference_inputs"

        # phase2_shadow路径（在inputs下）
        self.phase2_shadow_path = self.inputs_path / "phase2_shadow"
        self.fixtures_source_path = self.phase2_shadow_path / "fixtures" / "source"

        # R3: 回退路径——项目根目录下的phase2_shadow（开发环境）
        self._fallback_phase2_shadow = self.project_root / "phase2_shadow"
        self._fallback_fixtures_source = self._fallback_phase2_shadow / "fixtures" / "source"

    def get_input_file(self, name):
        """获取原始输入文件路径（R3: 支持reference_inputs和项目根phase2_shadow两种布局）"""
        # 1. 先在reference_inputs/phase2_shadow/fixtures/source下找
        p = self.fixtures_source_path / name
        if p.exists():
            return p
        # 2. 再在reference_inputs/phase2_shadow下找
        p = self.phase2_shadow_path / name
        if p.exists():
            return p
        # 3. R3回退：项目根目录phase2_shadow/fixtures/source
        p = self._fallback_fixtures_source / name
        if p.exists():
            return p
        # 4. R3回退：项目根目录phase2_shadow
        p = self._fallback_phase2_shadow / name
        if p.exists():
            return p
        # 兜底返回reference_inputs路径（即使不存在）
        return self.fixtures_source_path / name

    def __repr__(self):
        return "SnapshotConfig(root=%s, snapshot=%s, inputs=%s)" % (
            self.project_root, self.snapshot_path, self.inputs_path
        )


def load_json(path):
    """安全加载JSON"""
    path = Path(path)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_content_hash(data):
    """计算内容哈希（与导出端一致）"""
    content_for_hash = {k: v for k, v in data.items() if k != "content_hash"}
    return hashlib.sha256(
        json.dumps(content_for_hash, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]


def validate_snapshot_structure(data):
    """
    C2: 校验快照结构。
    返回 (is_valid, error_type, error_message, warnings)
    """
    warnings = []

    # 必须是dict
    if not isinstance(data, dict):
        return False, "SNAPSHOT_STRUCTURE_INVALID", "快照顶层不是JSON对象", warnings

    # 必需字段
    required_keys = ["trade_date", "market_overview", "market_metrics", "candidates"]
    missing_keys = [k for k in required_keys if k not in data]
    if missing_keys:
        return False, "SNAPSHOT_MISSING_KEYS", "快照缺少必需字段: %s" % ", ".join(missing_keys), warnings

    # candidates必须是list
    if not isinstance(data.get("candidates"), list):
        return False, "SNAPSHOT_INVALID_CANDIDATES", "candidates不是列表", warnings

    # market_metrics必须是list
    if not isinstance(data.get("market_metrics"), list):
        return False, "SNAPSHOT_INVALID_METRICS", "market_metrics不是列表", warnings

    return True, None, None, warnings


def validate_candidates(candidates, expected_trade_date=None):
    """
    Web02.1: 校验候选股：规范身份、日期一致性、重复键检测。
    605398和605398.SH视为同一只股票。
    同键不同内容隔离整个冲突组；异日记录隔离；完全相同重复去重并记录。
    返回 (valid_candidates, conflicts, errors, isolated)
    """
    return _validate_records(candidates, expected_trade_date, "candidate")


def _validate_records(records, expected_trade_date, record_type="record"):
    """
    Web02.1: 通用记录校验（候选/旧结果/影子结果共用）。
    规范身份后：异日隔离、同键不同内容整组隔离、完全相同去重。
    比较内容时排除单纯代码规范写法的差别。
    返回 (valid, conflicts, errors, isolated)
    """
    valid = []
    conflicts = []
    errors = []
    isolated = []

    if not isinstance(records, list):
        return valid, conflicts, ["%s列表不是数组" % record_type], isolated

    # 第一遍：收集所有规范身份键和索引
    key_indices = {}
    key_records = {}
    date_mismatch = []
    invalid_identity = []

    for idx, r in enumerate(records):
        if not isinstance(r, dict):
            errors.append("%s[%d]不是对象" % (record_type, idx))
            continue

        ts_code = r.get("ts_code", "")
        trade_date = r.get("trade_date", expected_trade_date)
        norm_code = normalize_code(ts_code)

        if norm_code is None:
            invalid_identity.append(idx)
            errors.append("%s[%d]代码%s无法规范化，已隔离" % (record_type, idx, ts_code))
            continue

        key = "%s_%s" % (trade_date, norm_code)

        if key not in key_indices:
            key_indices[key] = []
            key_records[key] = []
        key_indices[key].append(idx)
        key_records[key].append(r)

        # 日期一致性检查
        if expected_trade_date and trade_date and str(trade_date) != str(expected_trade_date):
            date_mismatch.append(idx)
            errors.append("%s[%s]日期%s与父级日期%s不一致，已隔离" % (record_type, norm_code, trade_date, expected_trade_date))

    # 第二遍：处理冲突和隔离
    isolated_indices = set(date_mismatch) | set(invalid_identity)

    for key, indices in key_indices.items():
        if len(indices) > 1:
            recs = key_records[key]
            # 比较内容时排除单纯代码规范写法的差别
            def _content_hash(r):
                r2 = dict(r)
                r2.pop("ts_code", None)  # 排除代码写法差别
                return json.dumps(r2, sort_keys=True, ensure_ascii=False)
            all_same = all(_content_hash(r) == _content_hash(recs[0]) for r in recs)
            if all_same:
                conflicts.append({
                    "key": key,
                    "ts_code": recs[0].get("ts_code", ""),
                    "normalized_code": normalize_code(recs[0].get("ts_code", "")),
                    "trade_date": recs[0].get("trade_date", ""),
                    "indices": indices,
                    "reason": "完全相同的重复记录，已去重保留1条（共%d条）" % len(indices),
                    "dedup": True,
                    "type": record_type,
                })
                for i in indices[1:]:
                    isolated_indices.add(i)
            else:
                conflicts.append({
                    "key": key,
                    "ts_code": recs[0].get("ts_code", ""),
                    "normalized_code": normalize_code(recs[0].get("ts_code", "")),
                    "trade_date": recs[0].get("trade_date", ""),
                    "indices": indices,
                    "reason": "同键不同内容，整个冲突组已隔离（共%d条）" % len(indices),
                    "dedup": False,
                    "type": record_type,
                })
                for i in indices:
                    isolated_indices.add(i)

    # 第三遍：构建有效列表和隔离列表
    # A1: 每条隔离记录追溯自己的类型、身份/日期或冲突组和原因，不使用首个冲突原因
    idx_to_conflict = {}
    idx_to_isolation_type = {}
    idx_to_reason = {}
    for c in conflicts:
        for i in c.get("indices", []):
            idx_to_conflict[i] = c
            if c.get("dedup"):
                idx_to_isolation_type[i] = "dedup"
                idx_to_reason[i] = "完全相同的重复记录，已去重合并（共%d条）" % len(c.get("indices", []))
            else:
                idx_to_isolation_type[i] = "conflict"
                idx_to_reason[i] = c.get("reason", "同键不同内容，冲突组已隔离")
    for i in date_mismatch:
        idx_to_isolation_type[i] = "date_mismatch"
        idx_to_reason[i] = "日期与父级不一致，已隔离"
    for i in invalid_identity:
        idx_to_isolation_type[i] = "invalid_identity"
        idx_to_reason[i] = "代码身份无法规范化，已隔离"

    for idx, r in enumerate(records):
        if not isinstance(r, dict):
            continue
        if idx in isolated_indices:
            norm_code = normalize_code(r.get("ts_code", ""))
            trade_date = r.get("trade_date", expected_trade_date)
            iso_type = idx_to_isolation_type.get(idx, "unknown")
            iso_reason = idx_to_reason.get(idx, "异日或身份非法")
            conflict_key = None
            if idx in idx_to_conflict:
                conflict_key = idx_to_conflict[idx].get("key")
            isolated.append({
                "index": idx,
                "record": r,
                "normalized_code": norm_code,
                "trade_date": trade_date,
                "isolation_type": iso_type,
                "conflict_key": conflict_key,
                "dedup": iso_type == "dedup",
                "reason": iso_reason,
                "type": record_type,
            })
            continue
        valid.append(r)

    return valid, conflicts, errors, isolated


def validate_metric(numerator, denominator, num_codes, den_codes, reported_value=None):
    """
    C3: 校验市场指标的合法性，包括分子必须属于分母。
    返回 (is_valid, calculated_value, error_reason, validation_details)
    """
    errors = []
    details = {}

    # 类型检查
    if isinstance(numerator, bool) or not isinstance(numerator, int):
        errors.append("分子不是整数: %r" % numerator)
    if isinstance(denominator, bool) or not isinstance(denominator, int):
        errors.append("分母不是整数: %r" % denominator)

    if errors:
        return False, None, "; ".join(errors), details

    # 负数检查
    if numerator < 0:
        errors.append("分子为负数: %d" % numerator)
    if denominator < 0:
        errors.append("分母为负数: %d" % denominator)

    # 分子大于分母
    if denominator > 0 and numerator > denominator:
        errors.append("分子(%d)大于分母(%d)" % (numerator, denominator))

    # R3 C3: 正计数配null成员判非法
    if numerator > 0 and num_codes is None:
        errors.append("分子计数>0但分子成员列表为null（无法验证成员）")
    if denominator > 0 and den_codes is None:
        errors.append("分母计数>0但分母成员列表为null（无法验证成员）")

    # 成员数量检查
    if num_codes is not None and numerator >= 0 and len(num_codes) != numerator:
        errors.append("分子成员数(%d)与分子计数(%d)不一致" % (len(num_codes), numerator))
    if den_codes is not None and denominator >= 0 and len(den_codes) != denominator:
        errors.append("分母成员数(%d)与分母计数(%d)不一致" % (len(den_codes), denominator))

    # 重复成员检查
    if num_codes and len(num_codes) != len(set(num_codes)):
        errors.append("分子成员存在重复")
    if den_codes and len(den_codes) != len(set(den_codes)):
        errors.append("分母成员存在重复")

    # C3: 分子必须属于分母
    if num_codes and den_codes and numerator > 0:
        num_set = set(num_codes)
        den_set = set(den_codes)
        not_in_den = num_set - den_set
        if not_in_den:
            errors.append("分子中有%d只股票不属于分母: %s" % (len(not_in_den), ", ".join(sorted(not_in_den)[:5])))
            details["numerator_not_in_denominator"] = sorted(not_in_den)

    if errors:
        details["errors"] = errors
        return False, None, "; ".join(errors), details

    # 计算值
    if denominator == 0:
        if numerator == 0:
            details["case"] = "ZERO_ZERO_NO_SAMPLE"
            return True, None, "0/0 无可比较样本", details
        else:
            details["case"] = "POSITIVE_OVER_ZERO_INVALID"
            return False, None, "正分子/0分母 非法", details

    calc_value = numerator / denominator * 100
    details["case"] = "VALID"
    details["calculated_from_members"] = bool(num_codes and den_codes)

    # 报告值对照
    if reported_value is not None and calc_value is not None:
        if abs(calc_value - reported_value) > 0.01:
            details["report_mismatch"] = {
                "calculated": calc_value,
                "reported": reported_value,
                "diff": abs(calc_value - reported_value),
            }

    return True, round(calc_value, 4), "", details


# 全局配置实例（懒加载）
_default_config = None


def get_config():
    """获取默认配置实例"""
    global _default_config
    if _default_config is None:
        _default_config = SnapshotConfig()
    return _default_config


def load_validation_data(config=None, requested_date=None):
    """
    C1+C2: 共享的快照读取与校验函数。
    返回 (data, load_status, errors)
    load_status: OK / FILE_MISSING / JSON_CORRUPTED / HASH_MISMATCH / STRUCTURE_INVALID / DATE_NOT_FOUND
    """
    if config is None:
        config = get_config()

    snapshot_path = config.snapshot_path

    # C2: 文件不存在
    if not snapshot_path.exists():
        return None, "FILE_MISSING", ["快照文件不存在: %s" % snapshot_path]

    # C2: JSON损坏
    try:
        with open(snapshot_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return None, "JSON_CORRUPTED", ["快照JSON解析失败: %s" % str(e)]
    except Exception as e:
        return None, "READ_ERROR", ["快照读取错误: %s" % str(e)]

    # C2: 结构校验
    is_valid, error_type, error_msg, warnings = validate_snapshot_structure(data)
    if not is_valid:
        return None, "STRUCTURE_INVALID", [error_msg]

    # C2 R3: content_hash为展示快照必需项；缺失、null、空串不能绕过验证
    stored_hash = data.get("content_hash")
    if not stored_hash or not isinstance(stored_hash, str) or stored_hash.strip() == "":
        return None, "HASH_MISSING", ["展示快照缺少content_hash字段，无法验证内容完整性"]

    # C2: content_hash校验
    computed_hash = compute_content_hash(data)
    if computed_hash != stored_hash:
        return None, "HASH_MISMATCH", [
            "内容哈希不匹配: 存储=%s, 计算=%s（内容可能被篡改）" % (stored_hash, computed_hash)
        ]

    # C2: 日期校验
    available_dates = []
    td = data.get("trade_date")
    if td:
        available_dates.append(str(td))

    if requested_date:
        if str(requested_date) not in available_dates:
            return None, "DATE_NOT_FOUND", [
                "请求日期%s不在可用日期列表%s中" % (requested_date, available_dates)
            ]

    # Web02.1: 三类记录统一校验（规范身份、隔离冲突）
    all_isolated = []
    all_conflicts = []
    all_errors = []

    # 候选股校验
    candidates = data.get("candidates", [])
    valid_candidates, cand_conflicts, cand_errors, cand_isolated = _validate_records(candidates, td, "candidate")
    data["candidates"] = valid_candidates
    if cand_conflicts:
        data["candidate_conflicts"] = cand_conflicts
        all_conflicts.extend(cand_conflicts)
    if cand_errors:
        data["candidate_errors"] = cand_errors
        all_errors.extend(cand_errors)
    if cand_isolated:
        all_isolated.extend(cand_isolated)

    # 旧模型结果校验
    legacy_results = data.get("legacy_results", [])
    if legacy_results:
        valid_legacy, legacy_conflicts, legacy_errors, legacy_isolated = _validate_records(legacy_results, td, "legacy")
        data["legacy_results"] = valid_legacy
        if legacy_conflicts:
            data["legacy_conflicts"] = legacy_conflicts
            all_conflicts.extend(legacy_conflicts)
        if legacy_errors:
            data["legacy_errors"] = legacy_errors
            all_errors.extend(legacy_errors)
        if legacy_isolated:
            all_isolated.extend(legacy_isolated)

    # 影子结果校验
    shadow_results = data.get("shadow_results", [])
    if shadow_results:
        valid_shadow, shadow_conflicts, shadow_errors, shadow_isolated = _validate_records(shadow_results, td, "shadow")
        data["shadow_results"] = valid_shadow
        if shadow_conflicts:
            data["shadow_conflicts"] = shadow_conflicts
            all_conflicts.extend(shadow_conflicts)
        if shadow_errors:
            data["shadow_errors"] = shadow_errors
            all_errors.extend(shadow_errors)
        if shadow_isolated:
            all_isolated.extend(shadow_isolated)

    # Web02.1: 统一隔离诊断集合
    if all_isolated:
        data["isolated_records"] = all_isolated
    if all_conflicts:
        data["all_conflicts"] = all_conflicts

    # C2: 合法空候选（candidates=[]但结构有效）不是错误
    if not candidates:
        data["empty_candidates"] = True
        data["empty_note"] = "该日无候选（快照合法，候选列表为空），市场指标仍正常展示"

    # 附加校验信息
    data["_load_status"] = "OK"
    data["_load_errors"] = []
    data["_load_warnings"] = warnings
    data["_available_dates"] = available_dates
    data["_snapshot_path"] = str(snapshot_path)

    return data, "OK", []
