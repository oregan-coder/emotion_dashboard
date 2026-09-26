import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from collection import fuyao_provider as provider


class Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload
        self.content = json.dumps(payload).encode()

    def json(self):
        return self.payload


class PoolSession:
    def __init__(self):
        self.calls = []

    def get(self, url, *, params, headers, timeout):
        self.calls.append((url, params, headers, timeout))
        page = params["page"]
        rows = [{"ticker": f"60000{page}", "name": "A", "last_price": 10.0}] if page < 3 else []
        return Response({"code": 0, "data": {"item": rows, "pagination": {"total": 2, "pages": 3, "page": page}}})


def test_pool_frame_collects_every_page_and_keeps_date_proof(monkeypatch):
    monkeypatch.setattr(provider, "api_key", lambda: "test-key")
    session = PoolSession()
    frame = provider.pool_frame("limit_up", "20260902", session=session)
    assert len(frame) == 2
    assert frame.attrs["source_date"] == "20260902"
    assert frame.attrs["complete"] is True
    assert len(session.calls) == 3
    assert all(call[2] == {"X-api-key": "test-key"} for call in session.calls)
    assert all("Authorization" not in call[2] for call in session.calls)


def test_pool_row_preserves_fuyou_limit_up_reason():
    row = provider._pool_row({"ticker": "600001", "limit_up_reason": "机器人+AIGC+机器人"}, "20260902")
    assert row["涨停原因"] == "机器人+AIGC+机器人"


def test_snapshot_rejects_incomplete_rows(monkeypatch):
    monkeypatch.setattr(provider, "api_key", lambda: "test-key")

    class Session:
        def get(self, *args, **kwargs):
            return Response({"code": 0, "data": {"item": [{"ticker": "600001"}], "total": 2}})

    try:
        provider.snapshot_rows(session=Session())
    except provider.FuyaoError as exc:
        assert "incomplete" in str(exc)
    else:
        raise AssertionError("incomplete snapshot was accepted")


def test_historical_cohort_uses_exact_provider_thscode(monkeypatch):
    monkeypatch.setattr(provider, "api_key", lambda: "test-key")
    previous, target = provider.day_ms("20260901"), provider.day_ms("20260902")

    class Session:
        def get(self, url, *, params, headers, timeout):
            assert params["thscode"] == "600001.SH"
            return Response({"code": 0, "data": {"item": [
                {"date_ms": previous, "close_price": 10.0},
                {"date_ms": target, "open_price": 10.2, "close_price": 11.0},
            ]}})

    frame = provider.historical_cohort_frame("20260902", "20260901", pd.DataFrame([
        {"代码": "600001", "名称": "A", "thscode": "600001.SH"},
    ]), session=Session())
    assert len(frame) == 1
    assert frame.iloc[0]["涨跌幅"] == 10.0


def test_historical_883900_uses_requested_and_previous_trading_days(monkeypatch):
    monkeypatch.setattr(provider, "api_key", lambda: "test-key")
    tz = ZoneInfo("Asia/Shanghai")
    previous = int(datetime(2026, 9, 1, tzinfo=tz).timestamp() * 1000)
    target = int(datetime(2026, 9, 2, tzinfo=tz).timestamp() * 1000)

    class Session:
        def get(self, *args, **kwargs):
            return Response({"code": 0, "data": {"thscode": "883900.TI", "interval": "1d", "item": [
                {"date_ms": previous, "close_price": 100.0},
                {"date_ms": target, "close_price": 105.0},
            ]}})

    result = provider.historical_883900("20260902", "20260901", session=Session())
    assert result["status"] == "VALID"
    assert result["source_date"] == "20260902"
    assert result["value"] == 5.0


def test_historical_883900_rejects_missing_requested_day(monkeypatch):
    monkeypatch.setattr(provider, "api_key", lambda: "test-key")
    previous = provider.day_ms("20260901")

    class Session:
        def get(self, *args, **kwargs):
            return Response({"code": 0, "data": {"thscode": "883900.TI", "interval": "1d", "item": [
                {"date_ms": previous, "close_price": 100.0},
            ]}})

    try:
        provider.historical_883900("20260902", "20260901", session=Session())
    except provider.FuyaoError as exc:
        assert "does not cover" in str(exc)
    else:
        raise AssertionError("missing target day was accepted")
