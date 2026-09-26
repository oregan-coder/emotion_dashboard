"""Rebuild one published money5 fact from frozen 883900 heads.

The result uses only the selected trade date and prior dates in the persisted
verified trading calendar.  It does not fetch, overwrite raw evidence, or read
any later session.  `--apply` is required for writes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


RULE = "5535_MONEY5_T4_PREVCLOSE_TO_T_CLOSE_V3"

def _ensure_published_history_view(conn):
    """Expose only current published and read-validated daily facts."""
    conn.execute(
        "CREATE VIEW IF NOT EXISTS v_money_effect_published AS "
        "SELECT d.trade_date, d.source_batch_id, d.run_id, d.rule_version, "
        "d.earning_effect, d.fund_cycle, d.fund_cycle_exact, d.stage, d.status "
        "FROM money_effect_daily d "
        "JOIN published_days p ON p.trade_date=d.trade_date AND p.batch_id=d.source_batch_id "
        "JOIN fact_read_gate g ON g.family='money5' AND g.trade_date=d.trade_date "
        "AND g.source_batch_id=d.source_batch_id "
        "WHERE d.status='VALID' AND g.status='MATCH'"
    )


def _stage(value):
    for edge, label in ((-2, "深度反击"), (2, "启动进攻"), (5, "均衡参与"),
                        (8, "动能减弱"), (13, "防御减仓"), (17, "退潮警戒")):
        if value <= edge:
            return label
    return "脉冲尾声"


def _calendar(conn, trade_date):
    row = conn.execute("SELECT value FROM m8839_meta WHERE key='tail_calendar_r1'").fetchone()
    if not row:
        raise ValueError("M8839_CALENDAR_MISSING")
    payload = json.loads(row[0])
    if payload.get("verified") is not True and payload.get("status") != "VALID":
        raise ValueError("M8839_CALENDAR_NOT_VERIFIED")
    days = sorted({str(item).replace("-", "") for item in payload.get("days", [])})
    if trade_date not in days:
        raise ValueError("TARGET_NOT_IN_VERIFIED_CALENDAR")
    index = days.index(trade_date)
    if index < 4:
        raise ValueError("FIVE_SESSION_WARMUP_MISSING")
    return days[index - 4:index + 1]


def preview(database: Path, trade_date: str):
    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        published = conn.execute(
            "SELECT p.batch_id FROM published_days p JOIN batches_fact b ON b.id=p.batch_id "
            "WHERE p.trade_date=? AND b.trade_date=?", (trade_date, trade_date)
        ).fetchone()
        if not published:
            raise ValueError("PUBLISHED_BATCH_MISSING")
        window = _calendar(conn, trade_date)
        marks = ",".join("?" for _ in window)
        rows = conn.execute(
            "SELECT h.trade_date,d.id,d.pct,d.close_value,d.preclose_value FROM m8839_heads h "
            "JOIN m8839_daily d ON d.id=h.revision_id WHERE h.trade_date IN (" + marks + ") "
            "ORDER BY h.trade_date", window
        ).fetchall()
        if [row["trade_date"] for row in rows] != window:
            raise ValueError("FROZEN_INDEX_HEAD_MISSING")
        if any(row["pct"] is None or row["close_value"] is None or row["preclose_value"] is None for row in rows):
            raise ValueError("FROZEN_INDEX_VALUE_MISSING")
        fund_cycle = round((rows[-1]["close_value"] / rows[0]["preclose_value"] - 1) * 100, 2)
        result = {
            "trade_date": trade_date,
            "source_batch_id": published["batch_id"],
            "rule_version": RULE,
            "earning_effect": rows[-1]["pct"],
            "fund_cycle": fund_cycle,
            "fund_cycle_exact": format(fund_cycle, ".2f"),
            "stage": _stage(fund_cycle),
            "status": "VALID",
            "window": [{"sequence_no": i, "window_date": row["trade_date"],
                        "earning_effect": row["pct"], "source_batch_ref": row["id"],
                        "status": "VALID"} for i, row in enumerate(rows)],
        }
        result["input_fingerprint"] = hashlib.sha256(
            json.dumps({"rule_version": RULE, "window": result["window"],
                        "fund_cycle_exact": result["fund_cycle_exact"]},
                       ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return result


def apply(database: Path, result):
    report = {"schema": "MONEY5_FROZEN_INDEX_HEAD_REPAIR_V1", "result": result,
              "generated_at": datetime.now(timezone.utc).isoformat()}
    report_sha256 = hashlib.sha256(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with sqlite3.connect(database, timeout=10) as conn:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_published_history_view(conn)
        conn.execute(
            "INSERT INTO money_effect_daily(trade_date,source_batch_id,run_id,rule_version,input_fingerprint,"
            "earning_effect,fund_cycle,fund_cycle_exact,stage,status,evidence_digest,evidence_locator) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(trade_date,source_batch_id) DO UPDATE SET "
            "run_id=excluded.run_id,rule_version=excluded.rule_version,input_fingerprint=excluded.input_fingerprint,"
            "earning_effect=excluded.earning_effect,fund_cycle=excluded.fund_cycle,"
            "fund_cycle_exact=excluded.fund_cycle_exact,stage=excluded.stage,status=excluded.status,"
            "evidence_locator=excluded.evidence_locator",
            (result["trade_date"], result["source_batch_id"], "repair:" + result["input_fingerprint"],
             result["rule_version"], result["input_fingerprint"], result["earning_effect"], result["fund_cycle"],
             result["fund_cycle_exact"], result["stage"], result["status"], None,
             "m8839_heads/" + ",".join(item["source_batch_ref"] for item in result["window"])),
        )
        conn.execute("DELETE FROM money_effect_window WHERE trade_date=? AND source_batch_id=?",
                     (result["trade_date"], result["source_batch_id"]))
        conn.executemany(
            "INSERT INTO money_effect_window(trade_date,source_batch_id,sequence_no,window_date,earning_effect,source_batch_ref,status) "
            "VALUES(?,?,?,?,?,?,?)",
            [(result["trade_date"], result["source_batch_id"], item["sequence_no"], item["window_date"],
              item["earning_effect"], item["source_batch_ref"], item["status"]) for item in result["window"]],
        )
        conn.execute("INSERT INTO reports(batch_id,kind,payload) VALUES(?,?,?) ON CONFLICT(batch_id,kind) DO UPDATE SET payload=excluded.payload",
                     (result["source_batch_id"], "money5_frozen_index_head_repair", json.dumps(report, ensure_ascii=False)))
        conn.execute(
            "INSERT INTO fact_read_gate(family,trade_date,source_batch_id,status,checked_at,report_sha256) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(family,trade_date,source_batch_id) DO UPDATE SET "
            "status=excluded.status,checked_at=excluded.checked_at,report_sha256=excluded.report_sha256",
            ("money5", result["trade_date"], result["source_batch_id"], "MATCH",
             datetime.now(timezone.utc).isoformat(), report_sha256),
        )
        conn.commit()
    return report_sha256


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    result = preview(args.database, args.date)
    output = {"status": "PREVIEW", "result": result}
    if args.apply:
        output["status"] = "APPLIED"
        output["report_sha256"] = apply(args.database, result)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
