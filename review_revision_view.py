# -*- coding: utf-8 -*-
"""P48 只读接入：从真实 SQLite 精确读取已保存的题材复核修订，构造独立展示面板。

- 只读（SELECT, uri mode=ro + PRAGMA query_only），不写库、不触发迁移、不联网。
- 目标修订固定 review_id=88d84cac...（P48 验收目标），按当前展示日期定位批次，
  批次不含该修订时返回未命中，绝不拿 20260914 作为其他日期/批次的兜底。
- 原研究记录（research_rows / reports）保持原样，本模块不修改任何业务表。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from review_revision_panel import ReviewKey, ReviewValidationError, build_panel, digest, read_json, validate_review
from review_revision_sqlite import (SQLiteLayout, ReviewNotFound, RepositoryError,
                                    UnsupportedLayout, fetch_exact_review, readonly_connection)

# P48 验收固定目标修订（7 股、14/14 确认、14 项参考分）
TARGET_REVIEW_ID = "88d84cac524bc2262903c811b10a02b690cf1f8f9d06b24ce4818ea1b957fbd5"
TARGET_BASE_BATCH = "42e50d3c1725423a99d4c317ab4bb689"
TARGET_TRADE_DATE = "20260914"
TARGET_PREVIOUS_DATE = "20260911"

REVISION_TABLE = SQLiteLayout(
    table="theme_factor_review_revisions",
    payload_column="payload_json",
    review_id_column="review_id",
    base_batch_id_column="base_batch_id",
    saved_at_column="saved_at",
)


def resolve_database_path(web_file: str | Path) -> Path:
    """从主站真实配置（5535_automation.json）读取数据库路径，不硬编码。"""
    config_path = Path(web_file).resolve().parent / "5535_automation.json"
    if not config_path.is_file():
        raise RepositoryError("5535_automation.json 缺失；数据库路径无从读取")
    cfg = json.loads(config_path.read_text(encoding="utf-8-sig"))
    db = cfg.get("database")
    if not db:
        raise RepositoryError("5535_automation.json 未配置 database 字段")
    db_path = Path(db).expanduser()
    if not db_path.is_absolute():
        db_path = config_path.parent / db_path
    return db_path.resolve()


def _lookup_target_revision(database: Path) -> dict:
    """只读确认目标修订在库且唯一匹配 review_id；返回 review_id/trade_date/previous。"""
    with readonly_connection(database) as conn:
        row = conn.execute(
            'SELECT review_id, base_batch_id, trade_date, previous_trade_date, saved_at '
            'FROM theme_factor_review_revisions WHERE review_id=?', (TARGET_REVIEW_ID,)).fetchone()
    if row is None:
        raise ReviewNotFound("目标修订未命中：该批次未读到该修订（不拿其他日期/修订兜底）")
    return {"review_id": row["review_id"], "base_batch_id": row["base_batch_id"],
            "trade_date": row["trade_date"], "previous_trade_date": row["previous_trade_date"],
            "saved_at": row["saved_at"]}


def _key_for_scope(base_batch_id: str, trade_date: str, previous_trade_date: str) -> ReviewKey:
    return ReviewKey(base_batch_id=base_batch_id, review_id=TARGET_REVIEW_ID,
                     trade_date=trade_date, previous_trade_date=previous_trade_date)


def build_panel_for_target(database: Path):
    """只读读取目标修订并构造展示面板。

    返回 (model, trace, scope)。当目标修订的批次与请求日期不一致时不展示。
    """
    row_meta = _lookup_target_revision(database)
    key = _key_for_scope(row_meta["base_batch_id"], row_meta["trade_date"], row_meta["previous_trade_date"])
    payload, evidence, trace = fetch_exact_review(database, REVISION_TABLE, key)
    model = build_panel(payload, key, evidence=evidence)
    scope = {"base_batch_id": key.base_batch_id, "review_id": key.review_id,
             "trade_date": key.trade_date, "previous_trade_date": key.previous_trade_date,
             "saved_at_as_stored": row_meta["saved_at"]}
    return model, trace, scope


def latest_published_date(database: Path) -> str:
    """主站实际展示的最新已发布交易日（published_days 表，真实库元数据）。

    与 automation Store 的 available_dates 同源，避免误用旧 build_dashboard() 日期。
    """
    with readonly_connection(database) as conn:
        row = conn.execute(
            'SELECT MAX(trade_date) AS d FROM published_days').fetchone()
    d = row["d"] if row else None
    if not d:
        raise ReviewNotFound("published_days 无已发布批次；无法确定主站展示范围")
    return d


def scope_is_target(base_batch_id: str, trade_date: str) -> bool:
    """判断当前展示范围是否为目标批次/日期，避免跨日兜底。"""
    return base_batch_id == TARGET_BASE_BATCH and trade_date == TARGET_TRADE_DATE


__all__ = ["resolve_database_path", "build_panel_for_target", "scope_is_target",
           "TARGET_REVIEW_ID", "TARGET_BASE_BATCH", "TARGET_TRADE_DATE", "TARGET_PREVIOUS_DATE"]
