import pandas as pd
from scoring import pool_analyzer

from scoring.candidate_score_fields import enrich_limit_up_score_fields
from scoring.three_board_model import _extract_stocks, evaluate_three_board, parse_limit_up_reason


def test_verified_supplement_fills_only_missing_candidate_fields():
    canonical = pd.DataFrame([{
        "代码": "603207", "连板数": 2, "最新价": 27.94,
        "首次封板时间": "09:30", "封板资金": 46511718,
        "成交额": None, "换手率": None, "炸板次数": None,
    }])
    source = pd.DataFrame([{
        "代码": "603207", "连板数": 2, "最新价": 27.94,
        "成交额": 365592000, "换手率": 24.1611, "炸板次数": 0,
        "流通市值": 1525606311.24, "所属行业": "化学制药",
    }])

    evidence = enrich_limit_up_score_fields(canonical, "20260902", fetch=lambda _: source)

    assert evidence["status"] == "VALID"
    assert evidence["matched_codes"] == ["603207"]
    assert canonical.loc[0, "成交额"] == 365592000
    assert canonical.loc[0, "换手率"] == 24.1611
    assert canonical.loc[0, "炸板次数"] == 0


def test_supplement_rejects_close_mismatch_without_writing_fields():
    canonical = pd.DataFrame([{"代码": "603207", "连板数": 2, "最新价": 27.94}])
    source = pd.DataFrame([{
        "代码": "603207", "连板数": 2, "最新价": 27.95,
        "成交额": 1, "换手率": 1, "炸板次数": 0,
    }])

    evidence = enrich_limit_up_score_fields(canonical, "20260902", fetch=lambda _: source)

    assert evidence["status"] == "NO_VERIFIED_CANDIDATE_MATCH"
    assert "成交额" not in canonical.columns


def test_empty_primary_response_defaults_open_break_count_with_explicit_evidence(monkeypatch):
    canonical = pd.DataFrame([{"代码": "603207", "连板数": 2, "最新价": 27.94}])
    monkeypatch.setattr("scoring.candidate_score_fields._cached_previous_limit_up_pool", lambda _: None)

    evidence = enrich_limit_up_score_fields(canonical, "20990101", fetch=lambda _: pd.DataFrame())

    assert evidence["status"] == "EMPTY_RESPONSE_WITH_USER_DEFAULT_OPEN_BREAK"
    assert canonical.loc[0, "炸板次数"] == 1
    assert evidence["defaulted_fields"]["603207"] == {
        "source": "USER_APPROVED_DEFAULT_WHEN_EASTMONEY_HISTORY_EMPTY",
        "fields": ["炸板次数"],
        "value": 1,
        "reason": "EASTMONEY_LIMIT_UP_POOL_EMPTY_RESPONSE",
    }
    assert canonical.attrs["candidate_score_field_evidence"] == evidence


def test_extract_stocks_accepts_hour_minute_seal_time():
    frame = pd.DataFrame([{
        "代码": "603207", "名称": "小方制药", "连板数": 2,
        "最新价": 27.94, "首次封板时间": "09:30", "最后封板时间": "09:30",
    }])

    assert _extract_stocks(frame)[0]["seal_time"] == "093000"
    assert _extract_stocks(frame)[0]["last_seal_time"] == "093000"


def test_limit_up_reason_is_ordered_primary_theme_evidence():
    frame = pd.DataFrame([{
        "代码": "603207", "名称": "小方制药", "连板数": 2,
        "最新价": 27.94, "涨停原因": "创新药 + AI医疗 + 创新药",
    }])

    assert parse_limit_up_reason("机器人+AIGC+机器人") == ["机器人", "AIGC"]
    stock = _extract_stocks(frame)[0]
    assert stock["reason_concepts"] == ["创新药", "AI医疗"]
    assert stock["concept_source"] == "THS_LIMIT_UP_REASON"


def test_three_board_uses_fuyou_reason_without_f10_fallback(monkeypatch):
    def unexpected_f10(*args, **kwargs):
        raise AssertionError("F10 must not replace a Fuyao limit-up reason")

    monkeypatch.setattr(pool_analyzer, "fetch_concepts", unexpected_f10)
    frame = pd.DataFrame([{
        "代码": "603207", "名称": "小方制药", "连板数": 2, "最新价": 27.94,
        "涨停原因": "创新药+AI医疗", "首次封板时间": "09:30", "最后封板时间": "09:30",
        "封板资金": 46511718, "成交额": 365592000, "换手率": 24.1611, "炸板次数": 0,
    }])

    cards = evaluate_three_board(frame, date="20260902", rate_23=30, highest_board=5,
                                 high_board_fail_rate=10, prior_limitup_continue_rate=40)

    assert cards[0]["concepts"] == ["创新药", "AI医疗"]
    assert cards[0]["top_concept"] == "创新药"
    assert cards[0]["concept_source"] == "THS_LIMIT_UP_REASON"
