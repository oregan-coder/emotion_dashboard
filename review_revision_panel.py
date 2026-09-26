"""Build a separate presentation model. Never recompute or mutate research scores.

Supports the supplied 5535_DATED_THEME_FACTOR_REVIEW_V1 export. This is a
framework-neutral integration component, not a patch for an unidentified app.
All display numbers come from explicit fields; zero is never treated as missing.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
import json
import math
import re
from typing import Any, Mapping

SCHEMA = "5535_DATED_THEME_FACTOR_REVIEW_V1"
READY_FACTOR = "REVIEWED_SET_REFERENCE_ONLY"
SUCCESS_STATES = {"THEME_FACTOR_REVIEW_SAVED", "THEME_REVIEW_ALREADY_SAVED"}
FACTOR_IDS = ("B03", "C02")
MAX_SCORES = {"B03": 18, "C02": 8}
COMPLETE_FIELDS = {"B03": "today_set_reviewed_as_complete", "C02": "previous_set_reviewed_as_complete"}


class ReviewValidationError(ValueError):
    """Data must not silently fall back to another date, draft, or revision."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReviewValidationError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(text: str) -> Any:
    def bad_constant(value: str) -> None:
        raise ReviewValidationError(f"Non-finite JSON value: {value}")
    return json.loads(text, object_pairs_hook=_pairs, parse_constant=bad_constant)


@dataclass(frozen=True)
class ReviewKey:
    base_batch_id: str
    review_id: str
    trade_date: str
    previous_trade_date: str

    def __post_init__(self) -> None:
        if not isinstance(self.base_batch_id, str) or not self.base_batch_id:
            raise ReviewValidationError("base_batch_id is required")
        if not isinstance(self.review_id, str) or not re.fullmatch(r"[0-9a-f]{64}", self.review_id):
            raise ReviewValidationError("review_id must be a full lower-case SHA-256")
        for value in (self.trade_date, self.previous_trade_date):
            if not isinstance(value, str) or not re.fullmatch(r"\d{8}", value):
                raise ReviewValidationError("Dates must be YYYYMMDD strings")
            datetime.strptime(value, "%Y%m%d")
        if self.previous_trade_date >= self.trade_date:
            raise ReviewValidationError("previous_trade_date must precede trade_date")

    def cache_key(self, database_identity: str) -> tuple[str, ...]:
        # A host cache must include the database and the complete batch/revision scope.
        return (database_identity, self.base_batch_id, self.trade_date,
                self.previous_trade_date, self.review_id)


@dataclass(frozen=True)
class ReadEvidence:
    """Only a trusted server-side repository may create DATABASE_READONLY evidence.

    Do not accept this object from browser JSON or an unverified result file.
    The supplied SQLite reader creates it after an exact one-row SELECT.
    """
    mode: str = "EXPORTED_SNAPSHOT"
    matched_key: ReviewKey | None = None
    matched_rows: int | None = None
    row_payload_sha256: str | None = None
    read_at: str | None = None
    saved_at_as_stored: str | None = None
    database_label: str | None = None


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise ReviewValidationError(message)


def _score(value: Any, maximum: int, label: str) -> int | float | None:
    if value is None:
        return None
    _need(type(value) in (int, float) and math.isfinite(value), f"{label}: finite number or null required")
    _need(0 <= value <= maximum, f"{label}: outside 0..{maximum}")
    return value


def _unique(items: Any, field: str, label: str) -> dict[str, dict[str, Any]]:
    _need(isinstance(items, list), f"{label}: list required")
    output = {}
    for item in items:
        _need(isinstance(item, dict), f"{label}: object required")
        value = item.get(field)
        _need(isinstance(value, str) and bool(value), f"{label}: {field} required")
        _need(value not in output, f"{label}: duplicate {field} {value}")
        output[value] = item
    return output


def validate_review(review: Mapping[str, Any], key: ReviewKey) -> None:
    _need(isinstance(review, dict), "Review must be a JSON object")
    _need(review.get("schema") == SCHEMA, "Unsupported review schema; add an explicit adapter")
    for field, expected in asdict(key).items():
        _need(review.get(field) == expected, f"Scope mismatch: {field}")
    identity = review.get("identity")
    _need(isinstance(identity, dict), "Missing identity")
    _need(digest(identity) == key.review_id, "Identity hash mismatch")
    _need(identity.get("base_batch_id") == key.base_batch_id, "Identity batch mismatch")
    draft = review.get("draft_as_supplied")
    _need(isinstance(draft, dict), "Missing source draft")
    _need(digest(draft) == identity.get("draft_hash"), "Draft hash mismatch")
    for field in ("base_batch_id", "trade_date", "previous_trade_date"):
        _need(draft.get(field) == getattr(key, field), f"Draft scope mismatch: {field}")
    _need(draft.get("rules_sha256") == identity.get("rules_sha256"), "Rules fingerprint mismatch")
    _need(review.get("approval_status") == "NOT_APPROVED", "Approval boundary changed")
    _need(review.get("strategy_status") == "NOT_ENABLED", "Strategy boundary changed")
    for field in ("formal_score", "research_rank"):
        _need(field in review and review[field] is None, f"Unexpected production value: {field}")
    for field in ("original_research_mutated", "quote_flags_changed", "writes_existing_business_tables"):
        _need(review.get(field) is False, f"Unexpected or missing write boundary: {field}")
    records = _unique(review.get("records"), "code", "records")
    drafts = _unique(draft.get("items"), "code", "draft.items")
    _need(set(records) == set(drafts), "Draft and result stock sets differ")
    for code, record in records.items():
        _need(bool(re.fullmatch(r"\d{6}", code)), "Stock codes must retain six digits")
        _need(record.get("user_theme") == drafts[code].get("proposed_theme"), f"Theme mismatch: {code}")
        for field in ("formal_score", "research_rank", "permission", "grade"):
            _need(field in record and record[field] is None, f"{code}: unexpected {field}")
        _need(type(record.get("original_numeric_items")) is int and record["original_numeric_items"] >= 0,
              f"{code}: missing original item count")
        _need(isinstance(record.get("original_module_scores"), dict), f"{code}: missing original modules")
        factors = _unique(record.get("factors"), "factor_id", f"{code}.factors")
        _need(set(factors) == set(FACTOR_IDS), f"{code}: expected exactly B03 and C02")
        original = _unique(record.get("original_theme_factors"), "factor_id", f"{code}.original_theme_factors")
        _need(set(original) == set(FACTOR_IDS), f"{code}: missing original factor snapshots")
        for fid, factor in factors.items():
            maximum = MAX_SCORES[fid]
            _need(factor.get("max_score") == maximum, f"{code}/{fid}: maximum changed")
            complete_field = COMPLETE_FIELDS[fid]
            _need(type(drafts[code].get(complete_field)) is bool, f"{code}: completeness must be boolean")
            _need(factor.get("user_complete_as_stored") is drafts[code][complete_field],
                  f"{code}/{fid}: completeness differs from draft")
            _need(factor.get("production_score") is None and factor.get("score") is None,
                  f"{code}/{fid}: reference score promoted to production")
            _need(factor.get("roles_add_points") is False, f"{code}/{fid}: role must not add points")
            _need(factor.get("source_verification_overridden") is False,
                  f"{code}/{fid}: source verification must not be overridden")
            reviewed = _score(factor.get("reviewed_set_reference_score"), maximum, f"{code}/{fid}")
            _score(factor.get("selected_set_reference_score"), maximum, f"{code}/{fid}/trial")
            if factor.get("status") == READY_FACTOR:
                _need(drafts[code][complete_field] is True, f"{code}/{fid}: ready without confirmation")
                _need(reviewed is not None, f"{code}/{fid}: ready without reviewed score")
                _need(not factor.get("blockers") and not factor.get("pending_members"),
                      f"{code}/{fid}: ready with blockers")


def _persistence(review: dict[str, Any], key: ReviewKey,
                 receipt: dict[str, Any] | None, evidence: ReadEvidence) -> dict[str, Any]:
    storage = review.get("storage_receipt")
    if storage is not None:
        _need(isinstance(storage, dict), "Invalid storage receipt")
        _need(storage.get("review_id") == key.review_id, "Storage receipt revision mismatch")
    if receipt is not None:
        _need(receipt.get("base_batch_id") == key.base_batch_id, "Run receipt batch mismatch")
        _need(receipt.get("review_id") == key.review_id, "Run receipt revision mismatch")
        _need(receipt.get("storage") == storage, "Two storage receipts disagree")
        _need(receipt.get("status") == (storage or {}).get("status")
              or receipt.get("status") == "CURRENT_DRAFT_CALCULATED", "Run/storage status conflict")
    if evidence.mode == "DATABASE_READONLY":
        _need(evidence.matched_key == key and evidence.matched_rows == 1,
              "Database read did not prove an exact unique revision match")
        _need(evidence.row_payload_sha256 == digest(review), "Database payload proof mismatch")
        _need(bool(evidence.read_at), "Database read time required")
        return {"state": "DATABASE_ROW_CONFIRMED", "label": "已保存 · 本次数据库只读回读确认",
                "saved": True, "verified_from_database_this_read": True,
                "source_storage_status": (storage or {}).get("status"),
                "input_saved_flag": review.get("database_saved"),
                "saved_at_as_stored": evidence.saved_at_as_stored,
                "note": "保存表中精确命中该修订；序列化载荷可能保留保存前阶段字段，不改写原载荷。"}
    _need(evidence.mode == "EXPORTED_SNAPSHOT", "Unsupported evidence mode")
    _need(evidence.matched_key is None and evidence.matched_rows is None,
          "Export preview must not impersonate a database read")
    status = (storage or {}).get("status")
    saved = review.get("database_saved") is True
    if saved or status in SUCCESS_STATES:
        _need(saved and status in SUCCESS_STATES, "Saved flag and export storage receipt conflict")
        exists = status == "THEME_REVIEW_ALREADY_SAVED"
        return {"state": "SAVED_REPORTED_ALREADY_EXISTS" if exists else "SAVED_REPORTED",
                "label": "已保存 · 应用回执确认（相同修订已存在）" if exists else "已保存 · 应用回执确认",
                "saved": True, "verified_from_database_this_read": False,
                "source_storage_status": status, "input_saved_flag": True,
                "saved_at_as_stored": None,
                "note": "依据已验收导出回执；本预览未连接用户数据库，不代表主站已经接入。"}
    return {"state": "CALCULATED_NOT_SAVED", "label": "计算完成 · 本导出未提供保存成功证据",
            "saved": False, "verified_from_database_this_read": False,
            "source_storage_status": status, "input_saved_flag": review.get("database_saved"),
            "saved_at_as_stored": None, "note": "不自动保存、不重新计算，不读取默认旧稿替代本结果。"}


def build_panel(review: dict[str, Any], key: ReviewKey, *,
                run_receipt: dict[str, Any] | None = None,
                evidence: ReadEvidence | None = None) -> dict[str, Any]:
    """Return a NEW model. No DB, network, calculation, save or host mutation occurs."""
    validate_review(review, key)
    evidence = evidence or ReadEvidence()
    persistence = _persistence(review, key, run_receipt, evidence)
    drafts = {x["code"]: x for x in review["draft_as_supplied"]["items"]}
    rows = []
    confirmed = ready_count = 0
    original_count = 0
    for record in sorted(review["records"], key=lambda x: x["code"]):
        code = record["code"]
        draft = drafts[code]
        ref = {}
        for factor in record["factors"]:
            fid = factor["factor_id"]
            complete = draft[COMPLETE_FIELDS[fid]]
            confirmed += int(complete)
            ready = (complete and factor.get("status") == READY_FACTOR
                     and not factor.get("blockers") and not factor.get("pending_members"))
            ready_count += int(ready)
            # No `x or fallback`: a legitimate 0.0 remains 0.0.
            visible = factor.get("reviewed_set_reference_score") if ready else None
            ref[fid] = {"factor_id": fid, "name": factor["name"],
                        "status": factor["status"], "complete": complete,
                        "display_score": visible, "max_score": factor["max_score"],
                        "trial_score_as_stored": factor.get("selected_set_reference_score"),
                        "values": deepcopy(factor.get("values", {})),
                        "formula": factor.get("formula"), "score_parts": deepcopy(factor.get("score_parts", {})),
                        "blockers": deepcopy(factor.get("blockers", [])),
                        "pending_members": deepcopy(factor.get("pending_members", [])),
                        "selected_codes": deepcopy(factor.get("selected_codes", [])),
                        "retained_codes": deepcopy(factor.get("retained_codes", [])),
                        "member_details": deepcopy(factor.get("member_details", [])),
                        "reference_note": factor.get("reference_note"),
                        "source_pointer": f"/records/{review['records'].index(record)}/factors/{record['factors'].index(factor)}"}
        original_count += record["original_numeric_items"]
        rows.append({"code": code, "name": record["name"], "theme": record["user_theme"],
                     "baseline_record_sha256_as_supplied": record.get("baseline_record_sha256"),
                     "original": {"module_scores": deepcopy(record["original_module_scores"]),
                                  "theme_factors": deepcopy(record["original_theme_factors"]),
                                  "numeric_items_as_supplied": record["original_numeric_items"],
                                  "research_score": record.get("original_research_score"),
                                  "screening_as_stored": deepcopy(record.get("screening_as_stored", {}))},
                     "reference": ref,
                     "remaining_independent_gaps": deepcopy(record.get("remaining_independent_gaps", [])),
                     "source_references_as_supplied": deepcopy(record.get("source_references_as_supplied", [])),
                     "source_references_independently_checked_by_tool": record.get("source_references_independently_checked_by_tool"),
                     "source_time_note": record.get("source_time_note")})
    if run_receipt is not None:
        completeness = run_receipt.get("completeness", {})
        _need(completeness.get("confirmed_sets") == confirmed, "Receipt confirmed-set count mismatch")
        _need(completeness.get("total_sets") == len(rows) * 2, "Receipt total-set count mismatch")
    return {"schema": "P48_THEME_REVIEW_PANEL_V1", "key": asdict(key),
            "title": "事后题材复核 · 独立研究修订",
            "persistence": persistence,
            "source": {"mode": evidence.mode, "database_label": evidence.database_label,
                       "read_at": evidence.read_at, "report_generated_at": review.get("created_at"),
                       "report_generated_at_note": "本次结果生成时间，不等于首次入库时间。",
                       "run_id": (run_receipt or {}).get("run_id"),
                       "original_full_records_rechecked": False,
                       "original_verification_note": "此载荷仅保留原分项计数及部分快照；主站须另做完整原研究前后比对。"},
            "counts": {"candidates": len(rows), "confirmed_sets": confirmed,
                       "total_sets": len(rows) * 2, "reviewed_reference_items": ready_count,
                       "original_numeric_items_as_supplied": original_count},
            "boundaries": {"approval_status": review["approval_status"],
                           "strategy_status": review["strategy_status"],
                           "formal_score": None, "research_rank": None,
                           "reference_scores_must_not_enter_original_totals": True},
            "limits": deepcopy(review.get("limits", [])), "rows": rows}
