from collection.market_breadth_store import summarize_daily_k_rows
from publish_completed_generation import _accept_verified_fuyou_breadth


def test_summarize_daily_k_rows_counts_signs_and_skips_no_prior_close_day():
    records, rows, skipped = summarize_daily_k_rows([
        {"date": "20260901", "thscode": "000001.SZ", "pct_change": ""},
        {"date": "20260901", "thscode": "000002.SZ", "pct_change": ""},
        {"date": "20260902", "thscode": "000001.SZ", "pct_change": "1.2"},
        {"date": "20260902", "thscode": "000002.SZ", "pct_change": "-0.3"},
        {"date": "20260902", "thscode": "000003.SZ", "pct_change": "0"},
        {"date": "20260902", "thscode": "000004.SZ", "pct_change": ""},
    ])
    assert rows == 6
    assert skipped == ["20260901"]
    assert records == [{
        "trade_date": "20260902", "up": 1, "down": 1,
        "flat": 1, "unknown": 1, "total": 4,
    }]


def test_summarize_daily_k_rows_rejects_duplicate_date_symbol():
    rows = [
        {"date": "20260902", "thscode": "000001.SZ", "pct_change": "1"},
        {"date": "20260902", "thscode": "000001.SZ", "pct_change": "2"},
    ]
    try:
        summarize_daily_k_rows(rows)
    except ValueError as exc:
        assert "重复日期证券" in str(exc)
    else:
        raise AssertionError("duplicate date/symbol was accepted")


def test_publish_gate_accepts_date_matched_local_daily_k_import():
    quality = {
        "status": "DATA_PENDING", "source_date_verified": True,
        "closing_verified": True, "scope_complete": True,
    }
    breadth = {
        "source": "HITHINK_LOCAL_A_SHARE_DAILY_K", "status": "VALID",
        "source_date": "20260901", "date_verified": True,
        "closing_verified": True, "complete": True,
        "up": 3, "down": 2, "flat": 1, "unknown": 0, "total": 6,
        "validation_evidence": {"import": {
            "source_batch_id": "LOCAL_DAILY_K_0123456789abcdef",
            "file_sha256": "a" * 64, "source_rows": 100, "imported_days": 38,
        }},
    }
    result = _accept_verified_fuyou_breadth(
        quality, {"date": "20260901"}, {"input_evidence": {"breadth": breadth}}
    )
    assert result["status"] == "VALID_MARKET_INPUT"
