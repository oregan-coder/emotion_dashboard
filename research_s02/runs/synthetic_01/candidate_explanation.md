# 候选研究解释｜合成候选，非真实证券（999999）

输入类型：**SYNTHETIC**。规则是待审提案，正式策略未启用。
观察日声明：2026-09-10；采样声明：SYNTHETIC_NOT_MARKET_CAPTURE。
源日期核实：False；收盘核实：False。
候选资格：**SYNTHETIC_ELIGIBLE**；依据：仅测试字段契约，不代表真实范围核实。

## 分项证据与得分
|项|预算|输入/单位|得分|数据状态及缺口|
|---|---:|---|---:|---|
|A01 昨日涨停表现|8|{"r_pct": 2.0}|5.0000|SYNTHETIC_ARITHMETIC|
|A02 已发生二进三承接|8|{"p23": 0.3}|4.8000|SYNTHETIC_ARITHMETIC|
|A03 高位续板保有|7|{"fail_high": 0.25}|5.2500|SYNTHETIC_ARITHMETIC|
|A04 市场封板稳定|4|{"U": 90, "Z": 30}|3.0000|SYNTHETIC_ARITHMETIC|
|A05 涨跌停两端力量|3|{"U": 90, "D": 10}|2.7000|SYNTHETIC_ARITHMETIC|
|B01 题材有效成员上涨广度|10|{"breadth": 0.7}|7.0000|SYNTHETIC_ARITHMETIC|
|B02 题材两日相对强度|12|{"excess_median_T": 1.0, "excess_median_previous": 1.0}|12.0000|SYNTHETIC_ARITHMETIC|
|B03 题材梯队规模与层次|18|{"n1": 3, "n2": 1, "n3plus": 1}|12.0000|SYNTHETIC_ARITHMETIC|
|C02 首板阶段相对先手|8|{"n": 6, "rank": 2.0}|6.4000|SYNTHETIC_ARITHMETIC|
|D01 最后封板后持续时间|10|{"remaining_session_minutes": 180.0}|7.5000|SYNTHETIC_ARITHMETIC|
|D02 当日开板次数|6|{"open_break_count": 1}|3.0000|SYNTHETIC_ARITHMETIC|
|D03 收盘封单相对规模|6|{"seal_amount": 6000000, "circulating_market_cap": 1000000000}|3.6000|SYNTHETIC_ARITHMETIC|

已验证输入的分项数：12/12。
有效分项小计：72.25；完整研究分：**72.25**。
没有可用分项时小计为null，不是0分；缺项不归一化，不生成完整排名。

## B03逐股组成
- n1：910000, 910001, 910002
- n2：910003
- n3plus：910004
分档：{'lower': 4, 'peer': 1, 'upper': 2, 'structure': 5}；B03=12。

## 三项观察与主线五步
C01、C03、D04只作说明，无隐性加扣分，也不是0分项。
主线第五步要先确定题材异动日t0；t0的下一交易日已发生且不晚于T时可提供历史反馈证据。T之后的信息只能用于后验验证；本例不自动选定t0。

## 结论
保留已知记录与未知原因。完整输入未通过时不输出完整评分；规则可供独立研究复算，不代表评级、仓位或交易放行。
