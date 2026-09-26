"""An OPTIONAL, explicit-schema SQLite adapter; no guessed tables or migrations.

Use the existing application's repository when its storage is normalized across
several tables. This adapter supports only a verified one-row JSON-payload table.
The user database was NOT supplied; its table/column layout remains unverified.
"""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Iterator

from review_revision_panel import (ReadEvidence, ReviewKey, ReviewValidationError,
                                   build_panel, digest, read_json, validate_review)


class RepositoryError(RuntimeError):
    pass


class ReviewNotFound(RepositoryError):
    """Keep original research visible; do not imply the old SAVE action failed."""


class UnsupportedLayout(RepositoryError):
    pass


@dataclass(frozen=True)
class SQLiteLayout:
    table: str
    payload_column: str
    review_id_column: str
    base_batch_id_column: str
    saved_at_column: str | None = None


def _quote(identifier: str) -> str:
    if not isinstance(identifier, str) or not identifier or "\0" in identifier:
        raise UnsupportedLayout("Invalid SQLite identifier")
    return '"' + identifier.replace('"', '""') + '"'


@contextmanager
def readonly_connection(database: str | Path) -> Iterator[sqlite3.Connection]:
    """Never create a missing DB; never change journal mode or run a migration."""
    path = Path(database).expanduser().resolve(strict=True)
    if not path.is_file():
        raise RepositoryError("Database path is not a regular file")
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True,
                           timeout=3.0, isolation_level=None)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        yield conn
    finally:
        # Closing rolls back the read transaction, releasing its snapshot.
        conn.close()


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    row = conn.execute("SELECT type, sql FROM sqlite_master WHERE name=?", (table,)).fetchone()
    if row is None or row["type"] != "table":
        raise UnsupportedLayout(f"Configured table not found: {table}")
    if "VIRTUAL TABLE" in (row["sql"] or "").upper():
        raise UnsupportedLayout("Virtual tables require the application's verified repository")
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({_quote(table)})")}


def inspect_schema(database: str | Path) -> dict[str, list[str]]:
    """Metadata only. No row scans, writes, network calls or auto-selected table."""
    with readonly_connection(database) as conn:
        names = [row["name"] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {name: sorted(_table_columns(conn, name)) for name in names}


def fetch_exact_review(database: str | Path, layout: SQLiteLayout,
                       key: ReviewKey) -> tuple[dict, ReadEvidence, dict]:
    """SELECT by both base batch and full review ID, then validate both dates.

    There is intentionally no ORDER BY latest-run, cross-batch fallback, INSERT,
    UPDATE, CREATE TABLE, initialization hook, or use of a default draft file.
    """
    needed = {layout.payload_column, layout.review_id_column, layout.base_batch_id_column}
    if layout.saved_at_column:
        needed.add(layout.saved_at_column)
    if len({layout.payload_column, layout.review_id_column, layout.base_batch_id_column}) != 3:
        raise UnsupportedLayout("Payload, review ID and batch ID must be different columns")
    with readonly_connection(database) as conn:
        columns = _table_columns(conn, layout.table)
        missing = needed - columns
        if missing:
            raise UnsupportedLayout(f"Configured columns not found: {sorted(missing)}")
        selects = sorted(needed)
        statement = (f"SELECT {', '.join(_quote(c) for c in selects)} FROM {_quote(layout.table)} "
                     f"WHERE {_quote(layout.base_batch_id_column)}=? "
                     f"AND {_quote(layout.review_id_column)}=? LIMIT 2")
        rows = conn.execute(statement, (key.base_batch_id, key.review_id)).fetchall()
        if not rows:
            raise ReviewNotFound("Exact revision not found in this configured database/table; no fallback performed")
        if len(rows) != 1:
            raise ReviewValidationError("Multiple rows for the exact batch/revision; refuse arbitrary selection")
        row = rows[0]
        raw = row[layout.payload_column]
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > 8 * 1024 * 1024:
            raise ReviewValidationError("Expected bounded UTF-8 JSON payload")
        payload = read_json(raw)
        validate_review(payload, key)
        stamp = row[layout.saved_at_column] if layout.saved_at_column else None
        if stamp is not None and not isinstance(stamp, str):
            raise ReviewValidationError("saved_at must be a stored string; adapt timestamp units explicitly")
        # Identity/draft hashes are not a signature over every calculated output.
        # Returning the actual row hash allows the host to compare with a separately
        # trusted export or its own payload-integrity policy without inventing proof.
        evidence = ReadEvidence(mode="DATABASE_READONLY", matched_key=key, matched_rows=1,
                                row_payload_sha256=digest(payload),
                                read_at=datetime.now(timezone.utc).isoformat(),
                                saved_at_as_stored=stamp,
                                database_label=Path(database).name)
        trace = {"operation": "SELECT", "database_access": "READ_ONLY", "matched_rows": 1,
                 "table": layout.table, "payload_column": layout.payload_column,
                 "base_batch_id": key.base_batch_id, "review_id": key.review_id,
                 "trade_date": key.trade_date, "previous_trade_date": key.previous_trade_date,
                 "row_payload_sha256": evidence.row_payload_sha256,
                 "read_at": evidence.read_at,
                 "statement": statement,
                 "statement_parameters": [key.base_batch_id, key.review_id],
                 "database_writes_by_this_adapter": 0,
                 "source_database_independently_identified": False,
                 "note": "Host must prove this is the production repository, not a temporary fixture DB."}
        return payload, evidence, trace


def load_panel(database: str | Path, layout: SQLiteLayout, key: ReviewKey) -> tuple[dict, dict]:
    payload, evidence, trace = fetch_exact_review(database, layout, key)
    return build_panel(payload, key, evidence=evidence), trace
