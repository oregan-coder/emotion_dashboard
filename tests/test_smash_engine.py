import pandas as pd

from smash_engine import calculate_smash_emotion


def test_user_fixed_formula_and_leader_names():
    yesterday = pd.DataFrame({"代码": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"],
                              "名称": list("ABCDEFGHIJ"), "连板数": [2, 2, 3, 3, 4, 4, 5, 5, 5, 5]})
    today = pd.DataFrame({"代码": ["1", "3", "5", "7", "8"], "名称": ["A", "C", "E", "G", "H"],
                         "连板数": [3, 4, 5, 6, 6]})
    result = calculate_smash_emotion(yesterday, today)
    # 50% + 50% + 50% + 50%，转小数求和、固定 ÷ 4 × 10 = 5.0。
    assert result.score == 5.0
    assert result.highest_board == 6
    assert result.highest_stock == "G|H"
