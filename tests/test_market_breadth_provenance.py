from pathlib import Path

from collection.market_breadth_store import import_daily_k_csv, read, upsert


def test_replay_upsert_preserves_local_daily_k_import_lineage(tmp_path: Path):
    csv_path = tmp_path / "daily.csv"
    csv_path.write_text(
        "date,thscode,pct_change\n20260901,000001.SZ,1\n20260901,000002.SZ,-1\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "breadth.sqlite3"
    imported = import_daily_k_csv(db_path, csv_path)

    assert upsert(db_path, {
        "trade_date": "20260901", "status": "VALID",
        "source": "HITHINK_LOCAL_A_SHARE_DAILY_K", "source_date": "20260901",
        "up": 1, "down": 1, "flat": 0, "unknown": 0,
    })

    assert read(db_path, "20260901")["source_batch_id"] == imported["source_batch_id"]
