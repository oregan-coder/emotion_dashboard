import pandas as pd

from analytics.leader_monitor import build_leader_monitor


def test_optional_leader_fields_do_not_hide_verified_ladder_data():
    limit_up = pd.DataFrame([
        {"代码": "600001", "名称": "甲股", "连板数": 4, "首次封板时间": "09:31",
         "封板资金": None, "换手率": None, "炸板次数": None},
        {"代码": "600002", "名称": "乙股", "连板数": 3, "首次封板时间": "09:35",
         "封板资金": None, "换手率": None, "炸板次数": None},
    ])

    result = build_leader_monitor(limit_up, pd.DataFrame(), pd.DataFrame())

    assert result["highest"]["name"] == "甲股"
    assert result["highest"]["board"] == 4
    assert [item["name"] for item in result["high_boards"]] == ["甲股", "乙股"]

def test_normalized_records_build_the_same_leader_structure():
    limit_up = pd.DataFrame([
        {"code": "600001", "name": "甲股", "board": 4, "seal_time": "09:31",
         "seal_amount": None, "turnover": None, "open_count": None},
        {"code": "600002", "name": "乙股", "board": 3, "seal_time": "09:35",
         "seal_amount": None, "turnover": None, "open_count": None},
    ])

    result = build_leader_monitor(limit_up, pd.DataFrame(), pd.DataFrame())

    assert result["highest"]["name"] == "甲股"
    assert result["highest"]["board"] == 4
    assert [item["name"] for item in result["high_boards"]] == ["甲股", "乙股"]
