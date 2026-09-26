"""Publish a completed original generation through the existing Store.ingest API."""
from __future__ import annotations

import hashlib
import importlib
import json
import math
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


def publish(project_dir, result):
    project = Path(project_dir).resolve()
    generation = project / "data" / "last_generation"
    bundle = json.loads((generation / "input.json").read_text("utf-8"))
    snapshot = json.loads((generation / "dashboard.json").read_text("utf-8"))
    manifest = json.loads((generation / "generation_manifest.json").read_text("utf-8"))
    trade_date = str(result.get("date") or snapshot.get("date") or "")
    if not (trade_date.isdigit() and len(trade_date) == 8 and snapshot.get("date") == trade_date and bundle.get("date") == trade_date):
        raise ValueError("GENERATION_DATE_MISMATCH")
    if result.get("status") == "DATA_PENDING":
        raise ValueError("PENDING_GENERATION_NOT_PUBLISHED")
    backup_root = project / "data" / "bu_route_r6_source_backups" / "81b6db5caae644b3bd4cd0b7a1b1865e"
    if not (backup_root / "automation5535" / "store.py").is_file():
        raise FileNotFoundError("STORE_INGEST_COMPATIBILITY_SOURCE_MISSING")
    sys.path.insert(0, str(backup_root))
    try:
        _install_store_common_module()
        Store = importlib.import_module("automation5535.store").Store
        quality = importlib.import_module("automation5535.normalization").quality
        source_quality = quality(bundle, snapshot)
        if source_quality.get("status") != "VALID_MARKET_INPUT":
            raise ValueError("PENDING_GENERATION_NOT_PUBLISHED")
        database = json.loads((project / "5535_automation.json").read_text("utf-8-sig"))["database"]
        from storage_retention import begin_capture, complete_capture
        capture_before = begin_capture(database)
        publication = Store(database).ingest(
            batch_id=uuid.uuid4().hex, trade_date=trade_date, mode="LIVE", bundle=bundle,
            snapshot=snapshot, manifest=manifest,
            input_hash=hashlib.sha256((generation / "input.json").read_bytes()).hexdigest(),
            snapshot_hash=hashlib.sha256((generation / "dashboard.json").read_bytes()).hexdigest(),
            engine_identity=hashlib.sha256((generation / "generation_manifest.json").read_bytes()).hexdigest(),
            generation_path=generation,
        )
        if not publication.get("deduplicated"):
            publication["storage"] = complete_capture(
                database, trade_date, publication["batch_id"], capture_before
            )
        publication["quality"] = source_quality
        return publication
    finally:
        for module_name in ("automation5535.store", "automation5535.normalization", "automation5535.common"):
            sys.modules.pop(module_name, None)
        sys.path.remove(str(backup_root))
