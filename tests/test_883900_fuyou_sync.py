import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from collection import fuyao_provider
from market_speed_883900.fuyao_sync import build_bundle


class Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload
        self.content = json.dumps(payload).encode("utf-8")

    def json(self):
        return self.payload


def _ms(day):
    return int(datetime.strptime(day, "%Y%m%d").replace(tzinfo=ZoneInfo("Asia/Shanghai")).timestamp() * 1000)


def test_historical_883900_range_preserves_raw_response_and_request_window(monkeypatch):
    monkeypatch.setattr(fuyao_provider, "api_key", lambda: "test-key")

    class Session:
        def get(self, url, *, params, headers, timeout):
            assert params["thscode"] == "883900.TI"
            assert params["start"] == _ms("20260826")
            assert params["end"] == _ms("20260902")
            assert headers == {"X-api-key": "test-key"}
            return Response({"code": 0, "data": {"thscode": "883900.TI", "interval": "1d", "item": [
                {"date_ms": _ms("20260826"), "close_price": 100.0},
                {"date_ms": _ms("20260827"), "close_price": 101.0},
            ]}})

    data, receipt, raw_text = fuyao_provider.historical_883900_range("20260826", "20260902", session=Session())
    assert data["thscode"] == "883900.TI"
    assert receipt["requested_start"] == "20260826"
    assert receipt["requested_end"] == "20260902"
    assert receipt["row_count"] == 2
    assert '"close_price": 101.0' in raw_text


def test_build_bundle_requires_every_verified_session_and_derives_daily_pct():
    calendar = ["20260826", "20260827", "20260828", "20260831", "20260901", "20260902"]

    def fetch(start, end):
        assert (start, end) == ("20260826", "20260902")
        rows = [{"date_ms": _ms(day), "close_price": 100.0 + index}
                for index, day in enumerate(calendar)]
        return ({"thscode": "883900.TI", "interval": "1d", "item": rows},
                {"url": "https://example.test/history", "request_id": "r1"}, json.dumps({"item": rows}))

    bundle = build_bundle(calendar, "20260827", "20260902", fetch=fetch)
    # 2026-08-26 is fetched as the verified prior close for the first
    # displayed day, but is not itself a derived daily-return record.
    assert [row["date"] for row in bundle["daily"]] == calendar[1:]
    assert bundle["daily"][-1]["preclose"] == 104.0
    assert bundle["daily"][-1]["pct"] == pytest.approx((105 / 104 - 1) * 100)
    assert bundle["response"]["provider"] == "FUYAO_883900_HISTORICAL"


def test_build_bundle_rejects_missing_verified_session():
    calendar = ["20260826", "20260827", "20260828", "20260831", "20260901", "20260902"]

    def fetch(start, end):
        rows = [{"date_ms": _ms(day), "close_price": 100.0 + index}
                for index, day in enumerate(calendar) if day != "20260831"]
        return ({"thscode": "883900.TI", "interval": "1d", "item": rows},
                {"url": "https://example.test/history"}, json.dumps({"item": rows}))

    with pytest.raises(ValueError, match="20260831"):
        build_bundle(calendar, "20260827", "20260902", fetch=fetch)
