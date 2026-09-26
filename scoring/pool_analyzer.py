# -*- coding: utf-8 -*-

"""
============================================================
A股打板情绪仪表盘 V3.1.1

涨停梯队与概念分析模块

功能：
1. 个股所属概念获取（东财F10，本地缓存，失败回退行业）
2. 2板个股：列出所属概念 + 同概念下今日1板涨停统计
3. 1板个股：按首次封板时间排序（最先涨停优先）+ 同概念今日涨停总数
4. 明日三板预案：从2板股中筛选
   条件：1板时强势（今日首封早/封板资金大）
        同概念今日批量涨停（板块效应）
        2板封板带动跟风上板、衍生新首板
============================================================
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pandas as pd
import requests

from core.board_utils import find_column, normalize_code


# ============================================================
# 配置
# ============================================================

F10_URL = (
    "https://emweb.securities.eastmoney.com"
    "/PC_HSF10/CoreConception/PageAjax"
)

CACHE_FILE = (
    Path(__file__).parent
    /
    "data"
    /
    "concept_cache.json"
)

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    ),
    "Referer": "https://emweb.securities.eastmoney.com/",
}


# 被动指数 / 通用标签 / 非题材类噪声（命中即剔除）
_NOISE_KEYWORDS = (
    "股通",
    "融资融券",
    "MSCI",
    "富时",
    "标普",
    "同花顺",
    "深成",
    "中证",
    "上证",
    "机构重仓",
    "基金重仓",
    "QFII",
    "社保",
    "信托重仓",
    "保险重仓",
    "转债",
    "破净",
    "破发",
    "破增发",
    "高市净率",
    "低市净率",
    "低价",
    "亏损",
    "扭亏",
    "高送转",
    "中报",
    "年报",
    "季报",
    "预盈",
    "预亏",
    "预增",
    "预减",
    "昨日",
    "百日",
    "新高",
    "多板",
    "热股",
    "题材股",
    "趋势股",
    "打板",
    "振幅",
    "次新",
    "ST",
    "举牌",
    "回购",
    "员工持股",
    "股权激励",
    "两融",
    "融资",
    "独角兽",
    "区块链",
    "小盘",
    "大盘",
    "中盘",
    "微盘",
    "贬值受益",
    "长江三角",
    "珠三角",
    "京津冀",
)

# 行业名（概念名完全等于时剔除）
_INDUSTRY_NAMES = (
    "计算机", "通信", "传媒", "出版", "教育", "游戏", "互联网",
    "软件", "半导体", "电子", "光学", "消费电子", "元件",
    "食品饮料", "饮料乳品", "非白酒", "其他酒类", "白酒", "酿酒",
    "化学制药", "生物制品", "医药", "医疗器械", "医疗服务", "中药",
    "化学制品", "化学原料", "化工", "钢铁", "煤炭", "石油", "燃气",
    "电力", "光伏", "风电", "电池", "电网", "家电", "小家电",
    "汽车", "摩托车", "航空", "机场", "航运", "港口", "铁路",
    "公路", "物流", "建筑", "装修", "建材", "水泥", "玻璃",
    "房地产", "物业", "银行", "证券", "保险", "信托", "租赁",
    "多元金融", "纺织", "服装", "鞋帽", "珠宝", "商业百货",
    "旅游", "酒店", "餐饮", "美容", "农业", "农林牧渔", "种植",
    "林业", "养殖", "饲料", "农产品", "渔业", "动物保健",
    "通用设备", "专用设备", "仪器仪表", "机械", "航天", "军工",
    "船舶", "环保", "公用事业",
)

# 地域板块（名称完全等于时剔除）
_REGION_NAMES = (
    "北京", "上海", "广东", "深圳", "江苏", "浙江", "山东",
    "福建", "湖南", "湖北", "河南", "河北", "四川", "重庆",
    "天津", "安徽", "江西", "广西", "云南", "贵州", "山西",
    "陕西", "甘肃", "青海", "宁夏", "新疆", "西藏", "内蒙古",
    "黑龙江", "吉林", "辽宁", "海南",
)


# ============================================================
# 概念缓存
# ============================================================

_cache = None


def _load_cache():
    global _cache
    if _cache is None:
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                _cache = json.load(f)
        except Exception:
            _cache = {}
    return _cache


def _save_cache():
    try:
        CACHE_FILE.parent.mkdir(exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_cache, f, ensure_ascii=False)
    except Exception:
        pass


# ============================================================
# 概念过滤
# ============================================================


def _is_noise(name: str, industry: str) -> bool:
    """
    判断板块名是否为噪声（被动指数/地域/行业细分/标签）
    """

    text = name.strip()

    if not text:
        return True

    # 地域板块（含"板块"后缀或单字地域名）
    if text.endswith("板块"):
        return True

    if text in _REGION_NAMES:
        return True

    # 行业细分（东财三级行业带罗马数字）
    if re.search(r"[ⅡⅢⅣⅤ]", text):
        return True

    # 行业名完全匹配
    if text in _INDUSTRY_NAMES:
        return True

    # 关键词噪声
    for kw in _NOISE_KEYWORDS:
        if kw in text:
            return True

    # 与所属行业相同 / 互为前缀（行业板块）
    if industry:
        ind = industry.strip()
        if text == ind:
            return True
        if len(text) >= 2 and ind.startswith(text):
            return True
        if len(ind) >= 2 and text.startswith(ind):
            return True

    return False


# ============================================================
# 个股概念获取
# ============================================================


def fetch_concepts(
    code: str,
    industry: str = "",
    date: str = "",
    session: requests.Session | None = None
) -> list[str]:
    """
    获取个股所属题材概念（东财F10）

    带本地缓存：data/concept_cache.json

    失败时回退为空列表（调用方用行业兜底）
    """

    code = normalize_code(code)

    if not code:
        return []

    cache = _load_cache()

    date_cache = cache.setdefault(date, {}) if date else cache

    if code in date_cache:
        return list(date_cache[code])

    # 东财代码前缀
    prefix = "SH" if code.startswith("6") else "SZ"

    session = session or requests.Session()

    concepts = []

    try:

        resp = session.get(
            F10_URL,
            params={"code": prefix + code},
            timeout=12,
            headers=REQUEST_HEADERS
        )

        data = resp.json()

        boards = data.get("ssbk", []) if isinstance(data, dict) else []

        for b in boards:

            name = str(b.get("BOARD_NAME", "")).strip()

            if not _is_noise(name, industry):

                concepts.append(name)

        # 去重保序
        seen = set()

        concepts = [
            c for c in concepts
            if not (c in seen or seen.add(c))
        ]

    except Exception:

        concepts = []

    # 概念为空时用行业兜底（打上行业前缀便于识别）
    if not concepts and industry:

        concepts = [industry]

    date_cache[code] = concepts

    _save_cache()

    return list(concepts)


# ============================================================
# 涨停池解析
# ============================================================


def _parse_pool(limit_up) -> list[dict]:
    """
    从原始涨停池 DataFrame 提取：

    code / name / board / seal_time / seal_amount / industry
    """

    if limit_up is None or not hasattr(limit_up, "empty") or limit_up.empty:
        return []

    code_col = find_column(
        limit_up,
        ["代码", "股票代码", "证券代码", "code"]
    )

    name_col = find_column(
        limit_up,
        ["名称", "股票名称", "证券简称", "name"]
    )

    board_col = find_column(
        limit_up,
        ["连板数", "连续涨停天数", "涨停统计", "板数", "board"]
    )

    time_col = find_column(
        limit_up,
        ["首次封板时间", "首封时间", "封板时间"]
    )

    amount_col = find_column(
        limit_up,
        ["封板资金", "封单资金"]
    )

    industry_col = find_column(
        limit_up,
        ["所属行业", "行业"]
    )

    if not code_col or not board_col:
        return []

    rows = []

    for _, row in limit_up.iterrows():

        code = normalize_code(row.get(code_col))

        if not code:
            continue

        board_text = str(row.get(board_col, "1"))

        nums = re.findall(r"\d+", board_text)

        board = int(nums[-1]) if nums else 1

        name = (
            str(row.get(name_col, code)).strip()
            if name_col
            else code
        )

        seal_time = ""

        if time_col:

            raw = str(row.get(time_col, "")).strip()

            digits = re.sub(r"\D", "", raw)

            if len(digits) == 6:
                seal_time = digits

        seal_amount = 0.0

        if amount_col:

            try:
                seal_amount = float(row.get(amount_col, 0) or 0)
            except Exception:
                seal_amount = 0.0

        industry = (
            str(row.get(industry_col, "")).strip()
            if industry_col
            else ""
        )

        rows.append({
            "code": code,
            "name": name,
            "board": board,
            "seal_time": seal_time,
            "seal_amount": seal_amount,
            "industry": industry
        })

    return rows


def _fmt_time(value: str) -> str:
    """
    092501 -> 09:25:01
    """

    digits = re.sub(r"\D", "", str(value))

    if len(digits) == 6:
        return f"{digits[:2]}:{digits[2:4]}:{digits[4:6]}"

    return str(value)


def _fmt_amount(value: float) -> str:
    """
    封板资金 -> 亿
    """

    if value >= 1e8:
        return f"{value / 1e8:.2f}亿"

    if value >= 1e4:
        return f"{value / 1e4:.0f}万"

    return "0"


# ============================================================
# 主分析入口
# ============================================================


def analyze_pool(
    limit_up,
    date: str = ""
) -> dict:
    """
    输出：
    {
      "second_board": [ {code,name,concepts,same_concept} ],
      "first_board":   [ {code,name,seal_time,seal_time_fmt,seal_amount,concepts,zt_counts} ],
      "tomorrow":      [ {code,name,concepts,score,reason} ]
    }
    """

    rows = _parse_pool(limit_up)

    if not rows:
        return {
            "second_board": [],
            "first_board": [],
            "tomorrow": []
        }

    # ----------
    # 获取概念（一次会话复用，循环取）
    # ----------

    session = requests.Session()

    concept_map = {}   # concept -> {code: name}  今日全部涨停股

    for r in rows:

        r["concepts"] = fetch_concepts(
            r["code"],
            r["industry"],
            date,
            session
        )

        for c in r["concepts"]:

            concept_map.setdefault(c, {})[r["code"]] = r["name"]

        time.sleep(0.05)

    # ----------
    # 今日各概念涨停统计
    # ----------

    def concept_total(c):
        return len(concept_map.get(c, {}))

    def concept_first(c):
        return sum(
            1
            for code in concept_map.get(c, {})
            if code in first_codes
        )

    first_codes = {
        r["code"]
        for r in rows
        if r["board"] == 1
    }

    # ----------
    # 2板个股 + 同概念1板统计
    # ----------

    second_board = []

    for r in rows:

        if r["board"] != 2:
            continue

        same = []

        for c in r["concepts"]:

            total = concept_total(c)

            first_list = [
                name
                for code, name in concept_map.get(c, {}).items()
                if code in first_codes
            ]

            if first_list:

                same.append({
                    "concept": c,
                    "first_count": len(first_list),
                    "first_stocks": first_list
                })

        same.sort(
            key=lambda x: -x["first_count"]
        )

        second_board.append({
            "code": r["code"],
            "name": r["name"],
            "seal_time": r["seal_time"],
            "seal_time_fmt": _fmt_time(r["seal_time"]),
            "seal_amount": r["seal_amount"],
            "seal_amount_fmt": _fmt_amount(r["seal_amount"]),
            "concepts": r["concepts"],
            "same_concept": same[:6]
        })

    # ----------
    # 1板个股（按首封时间升序，最先涨停优先）
    # ----------

    first_board = []

    for r in rows:

        if r["board"] != 1:
            continue

        zt_counts = [
            {
                "concept": c,
                "total": concept_total(c)
            }
            for c in r["concepts"]
        ]

        zt_counts.sort(
            key=lambda x: (-x["total"], x["concept"])
        )

        first_board.append({
            "code": r["code"],
            "name": r["name"],
            "seal_time": r["seal_time"],
            "seal_time_fmt": _fmt_time(r["seal_time"]),
            "seal_amount": r["seal_amount"],
            "seal_amount_fmt": _fmt_amount(r["seal_amount"]),
            "concepts": r["concepts"],
            "zt_counts": zt_counts[:5]
        })

    first_board.sort(key=lambda x: x["seal_time"])

    # ----------
    # 明日三板预案
    # ----------

    tomorrow = []

    for r in second_board:

        best = None

        for c in r["concepts"]:

            total = concept_total(c)

            first_count = concept_first(c)

            if best is None or (total + first_count) > (best[0] + best[1]):

                best = (total, first_count, c)

        if best is None:
            continue

        total, first_count, top_concept = best

        # 评分：概念涨停数 + 首板衍生数 + 封板强度
        score = total * 2 + first_count * 3

        # 首封时间越早越强
        if r["seal_time"] <= "093000":
            score += 30
        elif r["seal_time"] <= "100000":
            score += 20
        elif r["seal_time"] <= "103000":
            score += 10

        # 封板资金
        if r["seal_amount"] >= 2e8:
            score += 15
        elif r["seal_amount"] >= 1e8:
            score += 10
        elif r["seal_amount"] >= 5e7:
            score += 5

        # 板块效应不足的降权
        if total < 3:
            score -= 20

        effect = (
            "板块批量效应明显"
            if total >= 3
            else "板块效应一般"
        )

        reason = (
            f"今日首封{r['seal_time_fmt']}、封板资金{_fmt_amount(r['seal_amount'])}（强度参考）；"
            f"所属「{top_concept}」今日涨停{total}只，其中首板{first_count}只，{effect}；"
            "2板封板后有望带动跟风上板并衍生新首板。"
        )

        tomorrow.append({
            "code": r["code"],
            "name": r["name"],
            "concepts": r["concepts"],
            "top_concept": top_concept,
            "concept_zt": total,
            "first_zt": first_count,
            "score": score,
            "reason": reason
        })

    tomorrow.sort(key=lambda x: -x["score"])

    return {
        "second_board": second_board,
        "first_board": first_board,
        "tomorrow": tomorrow
    }


if __name__ == "__main__":

    import sys

    from collection.data_fetcher import _limit_up_pool

    target = sys.argv[1] if len(sys.argv) > 1 else "20260904"

    result = analyze_pool(
        _limit_up_pool(target),
        target
    )

    print("2板:", len(result["second_board"]))

    for r in result["second_board"]:
        print(r["name"], r["seal_time_fmt"], r["same_concept"][:3])

    print("1板:", len(result["first_board"]))

    for r in result["first_board"][:5]:
        print(r["name"], r["seal_time_fmt"], r["zt_counts"][:3])

    print("明日三板候选:")

    for r in result["tomorrow"]:
        print(r["name"], r["score"], r["reason"])
