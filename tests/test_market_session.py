from datetime import datetime
from zoneinfo import ZoneInfo

from collection import data_fetcher, fuyao_provider
import web_app


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _calendar(end_date, count):
    days = ["20260922", "20260923", "20260924"]
    return [day for day in days if day <= end_date][-count:]


def test_market_session_uses_latest_completed_day_on_non_trading_day(monkeypatch):
    monkeypatch.setattr(data_fetcher, "get_trade_dates", _calendar)
    result = data_fetcher.market_session(datetime(2026, 9, 26, 10, 0, tzinfo=SHANGHAI))
    assert result["today_is_trading_day"] is False
    assert result["update_enabled"] is True
    assert result["latest_completed_trade_date"] == "20260924"


def test_market_session_blocks_only_before_close_on_a_trading_day(monkeypatch):
    monkeypatch.setattr(data_fetcher, "get_trade_dates", _calendar)
    before = data_fetcher.market_session(datetime(2026, 9, 24, 14, 59, tzinfo=SHANGHAI))
    after = data_fetcher.market_session(datetime(2026, 9, 24, 15, 0, tzinfo=SHANGHAI))
    assert before["update_enabled"] is False
    assert before["latest_completed_trade_date"] == "20260923"
    assert after["update_enabled"] is True
    assert after["latest_completed_trade_date"] == "20260924"


def test_get_trade_dates_prefers_fuyao_calendar(monkeypatch):
    monkeypatch.setattr(fuyao_provider, "trading_days", lambda: ["20260923", "20260924"])
    monkeypatch.setattr(data_fetcher.ak, "tool_trade_date_hist_sina", lambda: (_ for _ in ()).throw(AssertionError()))
    assert data_fetcher.get_trade_dates("20260926", 2) == ["20260923", "20260924"]


def test_api_update_rejects_pre_close_latest_update(monkeypatch):
    monkeypatch.setattr(data_fetcher, "market_session", lambda: {
        "update_enabled": False,
        "reason": "当前交易日尚未收盘，15:00 后可更新当日数据",
        "latest_completed_trade_date": "20260923",
    })
    response = web_app.app.test_client().post("/api/update", json={})
    assert response.status_code == 409
    assert response.get_json()["error_type"] == "MARKET_NOT_CLOSED"
