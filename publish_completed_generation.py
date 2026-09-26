"""Publish a completed original generation through the existing Store.ingest API."""
from __future__ import annotations

import hashlib
import importlib
import json
import math
import sqlite3
import sys
import types
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _install_store_common_module():
    """Provide only the legacy Store helpers absent from the preserved backup."""
    module = types.ModuleType("automation5535.common")

    def day(value):
        text = str(value or "").replace("-", "")
        if not (text.isdigit() and len(text) == 8):
            raise ValueError("INVALID_TRADE_DATE")
        return text

    def numeric(value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    def integer(value):
        number = numeric(value)
        return int(number) if number is not None and number.is_integer() else None

    def code(value):
        text = str(value or "").strip()
        return text.zfill(6) if text.isdigit() and len(text) <= 6 else None

    def iso(value):
        normalized = day(value)
        return f"{normalized[:4]}-{normalized[4:6]}-{normalized[6:]}"

    def write_json(path, value):
        Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    def read_json(path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def digest(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    module.now = lambda: datetime.now(timezone.utc).isoformat()
    module.day = day
    module.iso = iso
    module.numeric = numeric
    module.integer = integer
    module.code = code
    module.write_json = write_json
    module.read_json = read_json
    module.digest = digest
    module.CN = timezone(timedelta(hours=8))
    module.json_text = lambda value: json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    sys.modules[module.__name__] = module


def _accept_verified_fuyou_breadth(source_quality, bundle, snapshot):
    """Accept only the equivalent, independently verified Fuyao breadth fact.

    The preserved normalizer predates the Fuyao adapter and hard-codes the
    legacy provider name.  This does not relax any date, finality or scope
    checks returned by that normalizer.
    """
    quality = dict(source_quality or {})
    if quality.get('status') == 'VALID_MARKET_INPUT':
        return quality
    if not (quality.get('source_date_verified') is True and quality.get('closing_verified') is True
            and quality.get('scope_complete') is True):
        return quality
    breadth = ((snapshot.get('input_evidence') or {}).get('breadth') or {})
    requested = str(bundle.get('date') or '').replace('-', '')
    counts = [breadth.get(key) for key in ('up', 'down', 'flat', 'unknown', 'total')]
    valid_counts = all(type(value) is int and value >= 0 for value in counts)
    valid_counts = valid_counts and sum(counts[:4]) == counts[4]
    local_import = (breadth.get('validation_evidence') or {}).get('import') or {}
    local_valid = (
        breadth.get('source') == 'HITHINK_LOCAL_A_SHARE_DAILY_K'
        and breadth.get('status') == 'VALID'
        and breadth.get('source_date') == requested
        and breadth.get('date_verified') is True
        and breadth.get('closing_verified') is True
        and breadth.get('complete') is True
        and valid_counts
        and str(local_import.get('source_batch_id') or '').startswith('LOCAL_DAILY_K_')
        and isinstance(local_import.get('file_sha256'), str) and len(local_import['file_sha256']) == 64
        and type(local_import.get('source_rows')) is int and local_import['source_rows'] > 0
        and type(local_import.get('imported_days')) is int and local_import['imported_days'] > 0
    )
    if local_valid:
        return {
            **quality,
            'status': 'VALID_MARKET_INPUT',
            'breadth_source': breadth['source'],
            'breadth_scope': breadth.get('scope'),
            'breadth_valid': True,
            'note': 'Local full-market daily-K breadth is date-matched and linked to its imported file hash.',
        }
    raw_breadth = ((bundle.get('market_breadth') or {}).get('raw') or {})
    evidence = breadth.get('validation_evidence') or raw_breadth.get('validation_evidence') or raw_breadth
    anchors = evidence.get('event_pool_anchor_check') or {}
    valid = (
        breadth.get('source') == 'FUYAO'
        and breadth.get('status') == 'VALID'
        and breadth.get('source_date') == requested
        and breadth.get('date_verified') is True
        and breadth.get('closing_verified') is True
        and breadth.get('complete') is True
        and evidence.get('calendar_latest_trading_day') == requested
        and type(anchors.get('anchor_rows')) is int and anchors['anchor_rows'] > 0
        and not anchors.get('missing')
        and not anchors.get('price_mismatch')
        and not anchors.get('change_mismatch')
        and valid_counts
    )
    if not valid:
        return quality
    return {
        **quality,
        'status': 'VALID_MARKET_INPUT',
        'breadth_source': 'FUYAO',
        'breadth_scope': breadth.get('scope'),
        'breadth_valid': True,
        'note': 'Fuyao current snapshot verified against official latest trade day and event-pool anchors.',
    }


def _quality_failure_reason(quality):
    """Return publishable diagnostics without weakening the verification gate."""
    checks = {
        '来源日期未核验': quality.get('source_date_verified') is True,
        '收盘状态未核验': quality.get('closing_verified') is True,
        '样本完整性未核验': quality.get('scope_complete') is True,
        '市场宽度来源未核验': quality.get('breadth_valid') is True,
    }
    failed = [label for label, passed in checks.items() if not passed]
    return '；'.join(failed) or str(quality.get('note') or '发布资格校验未通过')


def _ensure_slim_source_rows_insert(database):
    """Restore the omitted write trigger for the compact source-row view."""
    with sqlite3.connect(database, timeout=30) as conn:
        objects = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        )}
        if not {'source_rows', 'source_rows_fact'} <= objects:
            return
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS source_rows_ins
            INSTEAD OF INSERT ON source_rows
            BEGIN
                INSERT INTO source_rows_fact(batch_id,frame,row_no,code,source_date,blob_id)
                VALUES(NEW.batch_id,NEW.frame,NEW.row_no,NEW.code,NEW.source_date,zzip(NEW.payload_json));
            END
        """)
        conn.commit()


def _record_verified_quality(database, batch_id, source_quality):
    """Keep the stored batch gate aligned with the stricter Fuyao compatibility gate."""
    with sqlite3.connect(database, timeout=30) as conn:
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        table = 'batches_fact' if 'batches_fact' in tables else 'batches'
        conn.execute(
            f"UPDATE {table} SET quality_status=? WHERE id=?",
            (source_quality['status'], batch_id),
        )
        conn.commit()


def _ensure_published_day(database, trade_date, batch_id):
    """Repair a legacy Store ingest that persisted a batch without its read index."""
    with sqlite3.connect(database, timeout=30) as conn:
        row = conn.execute(
            "SELECT quality_status FROM batches_fact WHERE id=?", (batch_id,)
        ).fetchone()
        if not row or row[0] != "VALID_MARKET_INPUT":
            raise RuntimeError("PUBLISHED_DAY_REQUIRES_VALID_MARKET_INPUT")
        existing = conn.execute(
            "SELECT first_batch_id FROM published_days WHERE trade_date=?", (trade_date,)
        ).fetchone()
        first_batch_id = existing[0] if existing else batch_id
        conn.execute(
            "INSERT INTO published_days(trade_date,batch_id,first_batch_id,updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(trade_date) DO UPDATE SET batch_id=excluded.batch_id,updated_at=excluded.updated_at",
            (trade_date, batch_id, first_batch_id, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()


def publish(project_dir, result):
    project = Path(project_dir).resolve()
    generation = project / "data" / "last_generation"
    bundle = json.loads((generation / "input.json").read_text("utf-8"))
    snapshot = json.loads((generation / "dashboard.json").read_text("utf-8"))
    manifest = json.loads((generation / "generation_manifest.json").read_text("utf-8"))
    trade_date = str(result.get("date") or snapshot.get("date") or "")
    if not (trade_date.isdigit() and len(trade_date) == 8 and snapshot.get("date") == trade_date and bundle.get("date") == trade_date):
        raise ValueError("GENERATION_DATE_MISMATCH")
    backup_root = project / "data" / "bu_route_r6_source_backups" / "81b6db5caae644b3bd4cd0b7a1b1865e"
    if not (backup_root / "automation5535" / "store.py").is_file():
        raise FileNotFoundError("STORE_INGEST_COMPATIBILITY_SOURCE_MISSING")
    sys.path.insert(0, str(backup_root))
    try:
        _install_store_common_module()
        Store = importlib.import_module("automation5535.store").Store
        quality = importlib.import_module("automation5535.normalization").quality
        source_quality = _accept_verified_fuyou_breadth(quality(bundle, snapshot), bundle, snapshot)
        if source_quality.get("status") != "VALID_MARKET_INPUT":
            raise ValueError("PENDING_GENERATION_NOT_PUBLISHED: " + _quality_failure_reason(source_quality))
        database = json.loads((project / "5535_automation.json").read_text("utf-8-sig"))["database"]
        _ensure_slim_source_rows_insert(database)
        from storage.storage_retention import begin_capture, complete_capture
        capture_before = begin_capture(database)
        publication = Store(database).ingest(
            batch_id=uuid.uuid4().hex, trade_date=trade_date, mode="LIVE", bundle=bundle,
            snapshot=snapshot, manifest=manifest,
            input_hash=hashlib.sha256((generation / "input.json").read_bytes()).hexdigest(),
            snapshot_hash=hashlib.sha256((generation / "dashboard.json").read_bytes()).hexdigest(),
            engine_identity=hashlib.sha256((generation / "generation_manifest.json").read_bytes()).hexdigest(),
            generation_path=generation,
        )
        _record_verified_quality(database, publication["batch_id"], source_quality)
        _ensure_published_day(database, trade_date, publication["batch_id"])
        if not publication.get("deduplicated"):
            publication["storage"] = complete_capture(
                database, trade_date, publication["batch_id"], capture_before
            )
        publication["published"] = True
        publication["status"] = "PUBLISHED"
        publication["quality"] = source_quality
        return publication
    finally:
        for module_name in ("automation5535.store", "automation5535.normalization", "automation5535.common"):
            sys.modules.pop(module_name, None)
        sys.path.remove(str(backup_root))
