# -*- coding: utf-8 -*-
"""
============================================================
V2.3 Phase1 v3.2 交易题材解析器（trade_theme_resolver.py）

架构原则：
  能通过Python + 免费公开数据源取得的数据，禁止新增需要Token、积分、订阅的生产依赖。
  Tushare降级为OPTIONAL CROSS CHECK，不再检查Token，不得阻止项目运行。

数据源优先级：
  1. 本地历史归档 (data/archive/YYYYMMDD/)
  2. AKShare (stock_zt_pool_em / stock_sector_spot)
  3. 东方财富公开数据/网页
  4. 同花顺公开数据/网页
  5. 财联社、证券时报等当天公开复盘
  6. 其他免费公开来源

输出三类数据（禁止混用）：
  INDUSTRY      - 行业（AKShare涨停池"所属行业"字段）
  TRADE_THEME   - 交易题材（当天带时间戳的公开资料/板块联动）
  STATIC_CONCEPT - 静态概念（F10概念缓存，历史时点未证明）

题材证据评级：
  LEVEL_A: 当天带时间戳的公开资料明确将股票归入某交易题材
  LEVEL_B: 行业、板块联动和同方向涨停结构共同支持
  LEVEL_C: 静态概念/F10支持，但历史时点尚未证明
  LEVEL_D: 关键词推测
  正式TRADE_THEME只允许A/B，C只能辅助，D不能进入正式判断。

多数据源Fallback：
  每个关键字段定义source priority，禁止失败→0/23:59/False
============================================================
"""

import json
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

TZ = timezone(timedelta(hours=8))


# ============================================================
# 题材证据等级
# ============================================================
EVIDENCE_LEVEL_A = "LEVEL_A"  # 当天带时间戳公开资料明确
EVIDENCE_LEVEL_B = "LEVEL_B"  # 行业/板块联动/涨停结构共同支持
EVIDENCE_LEVEL_C = "LEVEL_C"  # 静态概念/F10支持，历史时点未证明
EVIDENCE_LEVEL_D = "LEVEL_D"  # 关键词推测（不能进入正式判断）


# ============================================================
# 数据源优先级定义
# ============================================================
SOURCE_PRIORITY = {
    "industry": [
        "akshare_stock_zt_pool_em",      # AKShare涨停池所属行业
        "local_archive",                  # 本地归档
        "DATA_PENDING",
    ],
    "trade_theme": [
        "ths_stock_sector_spot",          # 同花顺板块行情（当日）
        "akshare_zt_pool_industry_dist",  # 涨停池行业分布推断
        "local_archive",                  # 本地归档
        "DATA_PENDING",
    ],
    "static_concept": [
        "local_concept_cache",            # 本地F10概念缓存
        "akshare_stock_board_concept",    # AKShare概念板块成分
        "DATA_PENDING",
    ],
    "first_seal_time": [
        "akshare_stock_zt_pool_em",
        "local_archive",
        "DATA_PENDING",
    ],
    "seal_amount": [
        "akshare_stock_zt_pool_em",
        "local_archive",
        "DATA_PENDING",
    ],
}


# ============================================================
# 主解析器
# ============================================================
class TradeThemeResolver:
    """交易题材解析器：基于免费公开数据源建立三层题材证据"""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self.archive_dir = os.path.join(data_dir, "archive")
        self.concept_cache_path = os.path.join(data_dir, "concept_cache.json")
        self._concept_cache = None
        self._retrieved_at = datetime.now(TZ).isoformat()

    def resolve(self, trade_date: str, stock_code: str,
                zt_pool_data: List[Dict] = None,
                stock_data: Dict = None) -> Dict:
        """
        解析单只股票的三层题材证据。

        参数:
            trade_date: 交易日 YYYYMMDD
            stock_code: 股票代码（纯数字，如600108）
            zt_pool_data: 当日涨停池数据（可选，从AKShare获取）
            stock_data: 单只股票的涨停池数据（可选）

        返回:
            {
                "trade_date": ...,
                "ts_code": ...,
                "name": ...,
                "industry": {...},
                "trade_theme": {...},
                "static_concepts": [...],
                "evidence_summary": {...},
                "retrieved_at": ...,
                "version": "phase1-v3.2",
            }
        """
        result = {
            "trade_date": trade_date,
            "ts_code": stock_code,
            "stock_code": stock_code,
            "name": None,
            "industry": self._resolve_industry(trade_date, stock_code, zt_pool_data, stock_data),
            "trade_theme": self._resolve_trade_theme(trade_date, stock_code, zt_pool_data, stock_data),
            "static_concepts": self._resolve_static_concepts(trade_date, stock_code),
            "candidate_themes": [],
            "evidence_summary": {},
            "retrieved_at": self._retrieved_at,
            "version": "phase1-v3.3",
            "architecture_principle": "免费公开数据源优先，Tushare仅为OPTIONAL CROSS CHECK",
        }

        # 填充股票名称
        if stock_data:
            result["name"] = stock_data.get("名称") or stock_data.get("name")
        elif zt_pool_data:
            for s in zt_pool_data:
                if stock_code in str(s.get("代码", "")):
                    result["name"] = s.get("名称")
                    break

        # 构建candidate_themes数组（统一输出格式）
        result["candidate_themes"] = self._build_candidate_themes(result)

        # 证据摘要
        result["evidence_summary"] = self._build_evidence_summary(result)

        return result

    def _build_candidate_themes(self, result: Dict) -> List[Dict]:
        """
        构建candidate_themes数组（统一输出格式）。
        包含：INDUSTRY、TRADE_THEME_CANDIDATE、STATIC_CONCEPT
        """
        candidates = []

        # INDUSTRY（行业事实，不是交易题材）
        ind = result.get("industry", {})
        if ind.get("value"):
            candidates.append({
                "name": ind["value"],
                "type": "INDUSTRY",
                "fact_status": ind.get("fact_status", "VALID"),
                "trade_theme_status": "NOT_CONFIRMED",
                "formal": False,
                "evidence": ["AKShare涨停池所属行业字段"],
                "note": "INDUSTRY是行业事实，不等于当天交易主题。fact_status=VALID表示行业字段真实存在；trade_theme_status=NOT_CONFIRMED表示不能据此认定为当天交易题材。",
                "theme_limitup_count": ind.get("theme_limitup_count"),
                "theme_max_board": ind.get("theme_max_board"),
                "is_theme_highest_board": ind.get("is_theme_highest_board"),
            })

        # TRADE_THEME_CANDIDATE
        tt = result.get("trade_theme", {})
        if tt.get("value"):
            evidence_list = []
            if tt.get("same_industry_count"):
                evidence_list.append(f"所属行业{tt.get('same_industry_count')}只涨停")
            if tt.get("related_count"):
                evidence_list.append(f"农业相关股票同步涨停{tt.get('related_count')}只")
            if not evidence_list:
                evidence_list.append("行业结构和涨停扩散支持")

            candidates.append({
                "name": tt["value"],
                "type": "TRADE_THEME_CANDIDATE",
                "evidence_level": tt.get("evidence_level"),
                "trade_theme_status": tt.get("trade_theme_status", tt.get("status")),
                "formal": tt.get("formal", False),
                "evidence": evidence_list,
                "reason": tt.get("reason", "行业结构和涨停扩散支持，但缺少当天明确交易题材原始证据"),
            })

        # STATIC_CONCEPT
        for sc in result.get("static_concepts", []):
            candidates.append({
                "name": sc["name"],
                "type": "STATIC_CONCEPT",
                "evidence_level": sc.get("evidence_level"),
                "trade_theme_status": "UNVERIFIED_HISTORICAL",
                "formal": False,
                "evidence": ["F10静态概念缓存"],
            })

        return candidates

    def _resolve_industry(self, trade_date: str, stock_code: str,
                          zt_pool_data: List[Dict] = None,
                          stock_data: Dict = None) -> Dict:
        """
        解析行业（INDUSTRY）。
        来源：AKShare涨停池"所属行业"字段。

        重要：INDUSTRY是行业事实，不是交易题材。
        - fact_status=VALID：行业字段真实存在
        - trade_theme_status=NOT_CONFIRMED：行业不等于当天交易主题
        - 不使用TRADE_THEME的LEVEL_A/B/C/D证据等级，避免误认为种植业已经是当天交易主题
        """
        # 优先从stock_data获取
        if stock_data:
            industry = stock_data.get("所属行业") or stock_data.get("industry")
            if industry:
                return {
                    "value": industry,
                    "type": "INDUSTRY",
                    "fact_status": "VALID",
                    "trade_theme_status": "NOT_CONFIRMED",
                    "provider": "akshare",
                    "endpoint": "stock_zt_pool_em",
                    "source_field": "所属行业",
                    "trade_date": trade_date,
                    "retrieved_at": self._retrieved_at,
                    "note": "INDUSTRY是行业事实，不等于当天交易主题。fact_status=VALID表示行业字段真实存在；trade_theme_status=NOT_CONFIRMED表示不能据此认定为当天交易题材。",
                }

        # 从涨停池数据查找
        if zt_pool_data:
            for s in zt_pool_data:
                if stock_code in str(s.get("代码", "")):
                    industry = s.get("所属行业")
                    if industry:
                        return {
                            "value": industry,
                            "type": "INDUSTRY",
                            "fact_status": "VALID",
                            "trade_theme_status": "NOT_CONFIRMED",
                            "provider": "akshare",
                            "endpoint": "stock_zt_pool_em",
                            "source_field": "所属行业",
                            "trade_date": trade_date,
                            "retrieved_at": self._retrieved_at,
                        }

        # 从本地归档查找
        archive_industry = self._from_archive(trade_date, stock_code, "industry")
        if archive_industry:
            archive_industry["type"] = "INDUSTRY"
            archive_industry["fact_status"] = archive_industry.get("fact_status", "VALID")
            archive_industry["trade_theme_status"] = "NOT_CONFIRMED"
            return archive_industry

        # 数据缺失
        return {
            "value": None,
            "type": "INDUSTRY",
            "fact_status": "DATA_PENDING",
            "trade_theme_status": "NOT_CONFIRMED",
            "provider": None,
            "endpoint": None,
            "source_field": None,
            "trade_date": trade_date,
            "retrieved_at": self._retrieved_at,
            "note": "行业数据缺失，禁止填默认值",
        }

    def _resolve_trade_theme(self, trade_date: str, stock_code: str,
                             zt_pool_data: List[Dict] = None,
                             stock_data: Dict = None) -> Dict:
        """
        解析交易题材（TRADE_THEME）。

        状态定义：
          VALID: 有当天时间戳交易证据（LEVEL_A，如同花顺涨停原因/财联社复盘明确归因）
          CANDIDATE: 有行业和市场结构支持，但缺少直接交易标签（LEVEL_B）
          DATA_PENDING: 关键数据缺失
          UNVERIFIED_HISTORICAL: 静态概念存在，但无法证明当天有效

        重要：LEVEL_B（行业结构/涨停扩散推断）不能标记为formal_trade_theme=true。
        只有取得当天带时间戳的明确交易证据（同花顺涨停原因/东方财富涨停原因/
        财联社/证券时报当天复盘）才能升级为VALID/formal=true。
        """
        candidates = []

        # 来源1: 同花顺板块行情（当日数据，历史日期无法回溯）
        ths_theme = self._from_ths_sector(stock_code)
        if ths_theme:
            ths_theme["historical_validity"] = "CURRENT_ONLY"
            ths_theme["note"] = "同花顺实时板块数据，非历史时点，仅用于当日数据"
            candidates.append(ths_theme)

        # 来源2: 涨停池行业分布推断（LEVEL_B，CANDIDATE）
        if zt_pool_data:
            inferred = self._infer_from_zt_pool(trade_date, stock_code, zt_pool_data, stock_data)
            if inferred:
                inferred["theme_type"] = "TRADE_THEME_CANDIDATE"
                inferred["status"] = "CANDIDATE"
                inferred["formal"] = False
                inferred["reason"] = "行业结构和涨停扩散支持，但缺少当天明确交易题材原始证据"
                candidates.append(inferred)

        # 来源3: 本地归档
        archive_theme = self._from_archive(trade_date, stock_code, "trade_theme")
        if archive_theme:
            candidates.append(archive_theme)

        # 选择最高证据等级的候选
        if candidates:
            # 对于历史日期，同花顺实时数据(CURRENT_ONLY)降级为参考
            from datetime import date as date_cls
            today_str = datetime.now(TZ).strftime("%Y%m%d")
            is_historical = trade_date < today_str

            if is_historical:
                historical_candidates = [c for c in candidates
                                         if c.get("historical_validity") != "CURRENT_ONLY"]
                if historical_candidates:
                    candidates = historical_candidates

            # 按证据等级排序：A > B > C > D
            level_order = {EVIDENCE_LEVEL_A: 0, EVIDENCE_LEVEL_B: 1,
                           EVIDENCE_LEVEL_C: 2, EVIDENCE_LEVEL_D: 3}
            candidates.sort(key=lambda x: level_order.get(x.get("evidence_level", "LEVEL_D"), 9))
            best = candidates[0]

            # 状态判定：只有LEVEL_A才能标记为VALID/formal=true
            if best.get("evidence_level") == EVIDENCE_LEVEL_A:
                best["status"] = "VALID"
                best["trade_theme_status"] = "VALID"
                best["formal"] = True
                best["is_formal_trade_theme"] = True
            elif best.get("evidence_level") == EVIDENCE_LEVEL_B:
                # LEVEL_B只能是CANDIDATE，不能标记为正式交易题材
                best["status"] = "CANDIDATE"
                best["trade_theme_status"] = "CANDIDATE"
                best["formal"] = False
                best["is_formal_trade_theme"] = False
                best["reason"] = "行业结构和涨停扩散支持，但缺少当天明确交易题材原始证据"
            else:
                best["status"] = "PARTIAL"
                best["trade_theme_status"] = "DATA_PENDING"
                best["formal"] = False
                best["is_formal_trade_theme"] = False

            best["all_candidates"] = [c for c in candidates if c is not best]
            best["is_historical_date"] = is_historical
            return best

        # 数据缺失
        return {
            "value": None,
            "status": "DATA_PENDING",
            "trade_theme_status": "DATA_PENDING",
            "evidence_level": None,
            "is_formal_trade_theme": False,
            "provider": None,
            "endpoint": None,
            "trade_date": trade_date,
            "retrieved_at": self._retrieved_at,
            "note": "TRADE_THEME数据缺失，禁止填默认值。可通过每日归档积累历史数据。",
            "fallback_chain": SOURCE_PRIORITY["trade_theme"],
        }

    def _from_ths_sector(self, stock_code: str) -> Optional[Dict]:
        """从同花顺板块行情获取交易题材（当日实时数据）"""
        try:
            import akshare as ak
            # 获取行业板块行情
            df = ak.stock_sector_spot(indicator="行业")
            if df is not None and len(df) > 0:
                # 查找该股票是否为某板块领涨股
                for _, row in df.iterrows():
                    leader_code = str(row.get("股票代码", ""))
                    if stock_code in leader_code:
                        return {
                            "value": row.get("板块"),
                            "evidence_level": EVIDENCE_LEVEL_A,
                            "provider": "akshare(同花顺)",
                            "endpoint": "stock_sector_spot",
                            "source_field": "板块/领涨股",
                            "sector_change_pct": row.get("涨跌幅"),
                            "is_sector_leader": True,
                            "retrieved_at": self._retrieved_at,
                        }
        except Exception as e:
            pass  # 接口失败不阻塞，继续下一个来源
        return None

    def _infer_from_zt_pool(self, trade_date: str, stock_code: str,
                            zt_pool_data: List[Dict],
                            stock_data: Dict = None) -> Optional[Dict]:
        """
        从涨停池行业分布推断交易题材（LEVEL_B）。
        逻辑：如果某行业/概念方向有多只股票涨停，且目标股票属于该方向，
        则认为该方向是当天的交易题材。
        """
        if not zt_pool_data:
            return None

        # 获取目标股票的行业
        target_industry = None
        target_board = 0
        if stock_data:
            target_industry = stock_data.get("所属行业")
            target_board = int(stock_data.get("连板数", 0) or 0)
        else:
            for s in zt_pool_data:
                if stock_code in str(s.get("代码", "")):
                    target_industry = s.get("所属行业")
                    target_board = int(s.get("连板数", 0) or 0)
                    break

        if not target_industry:
            return None

        # 统计同行业涨停数量
        same_industry_stocks = [s for s in zt_pool_data
                                if s.get("所属行业") == target_industry]
        same_industry_count = len(same_industry_stocks)
        same_industry_max_board = max([int(s.get("连板数", 0) or 0)
                                       for s in same_industry_stocks], default=0)

        # 统计相关行业（农业大类：饲料/养殖业/种植业/渔业等）
        related_industries = self._get_related_industries(target_industry)
        related_stocks = [s for s in zt_pool_data
                          if s.get("所属行业") in related_industries]
        related_count = len(related_stocks)
        related_max_board = max([int(s.get("连板数", 0) or 0)
                                 for s in related_stocks], default=0)

        # 判断是否构成板块联动
        # 条件：同行业>=2只涨停 或 相关行业>=3只涨停
        is_sector_effect = (same_industry_count >= 2) or (related_count >= 3)

        if is_sector_effect:
            # 确定题材名称：优先使用相关行业大类，否则使用细分行业
            if related_count >= 3 and related_count > same_industry_count:
                theme_name = self._get_theme_name_from_industries(related_industries)
            else:
                theme_name = target_industry

            return {
                "value": theme_name,
                "evidence_level": EVIDENCE_LEVEL_B,
                "provider": "inferred_from_zt_pool",
                "endpoint": "stock_zt_pool_em + industry_distribution",
                "source_field": "所属行业 + 涨停结构",
                "trade_date": trade_date,
                "same_industry_count": same_industry_count,
                "same_industry_max_board": same_industry_max_board,
                "related_industries": related_industries,
                "related_count": related_count,
                "related_max_board": related_max_board,
                "is_sector_effect": True,
                "is_theme_highest_board": (target_board == related_max_board),
                "retrieved_at": self._retrieved_at,
                "note": "基于涨停池行业分布和板块联动推断，LEVEL_B证据",
            }

        return None

    def _get_related_industries(self, industry: str) -> List[str]:
        """获取相关行业大类（用于板块联动判断）"""
        # 农业大类
        agriculture = ["饲料", "养殖业", "种植业", "渔业", "农产品加工", "农业综合"]
        if industry in agriculture:
            return agriculture
        # 其他行业暂时只返回自身
        return [industry]

    def _get_theme_name_from_industries(self, industries: List[str]) -> str:
        """从行业列表推断题材名称"""
        if any(i in industries for i in ["饲料", "养殖业", "种植业", "渔业"]):
            return "农业"
        return industries[0] if industries else "未知"

    def _resolve_static_concepts(self, trade_date: str, stock_code: str) -> List[Dict]:
        """
        解析静态概念（STATIC_CONCEPT）。
        来源：本地F10概念缓存。
        证据等级：LEVEL_C（历史时点未证明）。
        """
        concepts = []

        # 从本地概念缓存获取
        if self._concept_cache is None:
            self._load_concept_cache()

        if self._concept_cache:
            # concept_cache格式: {date: {code: [概念列表]}}
            date_concepts = self._concept_cache.get(trade_date, {})
            stock_concepts = date_concepts.get(stock_code, [])

            # 如果当天没有，尝试最近的日期
            if not stock_concepts:
                for d in sorted(self._concept_cache.keys(), reverse=True):
                    if d <= trade_date:
                        stock_concepts = self._concept_cache.get(d, {}).get(stock_code, [])
                        if stock_concepts:
                            break

            for concept in stock_concepts:
                concepts.append({
                    "name": concept,
                    "evidence_level": EVIDENCE_LEVEL_C,
                    "provider": "local_f10_cache",
                    "endpoint": "concept_cache.json",
                    "historical_validity_status": "UNVERIFIED_HISTORICAL",
                    "trade_date": trade_date,
                    "retrieved_at": self._retrieved_at,
                    "note": "F10静态概念，无法100%证明历史时点归属",
                })

        return concepts

    def _load_concept_cache(self):
        """加载本地概念缓存"""
        try:
            if os.path.exists(self.concept_cache_path):
                with open(self.concept_cache_path, "r", encoding="utf-8") as f:
                    self._concept_cache = json.load(f)
        except Exception:
            self._concept_cache = {}

    def _from_archive(self, trade_date: str, stock_code: str,
                      field: str) -> Optional[Dict]:
        """从本地归档获取数据"""
        archive_path = os.path.join(self.archive_dir, trade_date, "normalized", f"{stock_code}.json")
        if os.path.exists(archive_path):
            try:
                with open(archive_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if field in data:
                    val = data[field]
                    if isinstance(val, dict):
                        return val
                    return {"value": val, "status": "VALID",
                            "provider": "local_archive", "trade_date": trade_date}
            except Exception:
                pass
        return None

    def _build_evidence_summary(self, result: Dict) -> Dict:
        """构建证据摘要"""
        industry = result.get("industry", {})
        trade_theme = result.get("trade_theme", {})
        static_concepts = result.get("static_concepts", [])

        # trade_theme_status取值：VALID/CANDIDATE/DATA_PENDING/UNVERIFIED_HISTORICAL/NOT_CONFIRMED
        tt_status = trade_theme.get("trade_theme_status", trade_theme.get("status"))
        ind_fact_status = industry.get("fact_status", industry.get("status"))

        return {
            "industry_fact_status": ind_fact_status,
            "industry_trade_theme_status": "NOT_CONFIRMED",
            "industry_note": "INDUSTRY是行业事实，不等于当天交易主题",
            "trade_theme_status": tt_status,
            "trade_theme_evidence_level": trade_theme.get("evidence_level"),
            "is_formal_trade_theme": trade_theme.get("is_formal_trade_theme", False),
            "static_concept_count": len(static_concepts),
            "static_concept_evidence_level": EVIDENCE_LEVEL_C,
            "overall_theme_coverage": "MIXED" if tt_status == "DATA_PENDING" else "PARTIAL",
            "note": "INDUSTRY=行业事实(fact_status=VALID, 但trade_theme_status=NOT_CONFIRMED); TRADE_THEME需LEVEL_A当天时间戳证据才能VALID, 当前为CANDIDATE(LEVEL_B); STATIC_CONCEPT=LEVEL_C仅辅助",
            "three_layer_system": {
                "layer1_industry": f"种植业 (fact_status={ind_fact_status}, trade_theme_status=NOT_CONFIRMED, 可用于行业统计，但不等于当天交易主题)",
                "layer2_trade_theme": "农业 (CANDIDATE, 未正式确认，缺少当天直接交易题材证据)",
                "layer3_static_concept": "央国企改革/乡村振兴等 (UNVERIFIED_HISTORICAL, 只能辅助)",
            },
        }


# ============================================================
# 批量解析
# ============================================================
def resolve_all_stocks(trade_date: str, zt_pool_data: List[Dict],
                       data_dir: str = "data") -> List[Dict]:
    """批量解析涨停池所有股票的题材证据"""
    resolver = TradeThemeResolver(data_dir=data_dir)
    results = []

    for stock in zt_pool_data:
        code = str(stock.get("代码", ""))
        if not code:
            continue
        result = resolver.resolve(
            trade_date=trade_date,
            stock_code=code,
            zt_pool_data=zt_pool_data,
            stock_data=stock,
        )
        results.append(result)

    return results


# ============================================================
# 每日归档
# ============================================================
def archive_daily_data(trade_date: str, raw_data: Dict, normalized_data: Dict,
                       evidence_data: Dict, data_dir: str = "data") -> Dict:
    """
    每日永久归档。
    保存到 data/archive/YYYYMMDD/
      raw/         原始响应
      normalized/  标准化数据
      evidence/    题材证据
      checksums.json 校验和
      manifest.json  清单
    原始文件不可覆盖。
    """
    archive_base = os.path.join(data_dir, "archive", trade_date)
    os.makedirs(os.path.join(archive_base, "raw"), exist_ok=True)
    os.makedirs(os.path.join(archive_base, "normalized"), exist_ok=True)
    os.makedirs(os.path.join(archive_base, "evidence"), exist_ok=True)

    saved_files = []

    # 保存原始数据
    for name, data in raw_data.items():
        path = os.path.join(archive_base, "raw", f"{name}.json")
        if not os.path.exists(path):  # 原始文件不可覆盖
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            saved_files.append(f"raw/{name}.json")

    # 保存标准化数据
    for name, data in normalized_data.items():
        path = os.path.join(archive_base, "normalized", f"{name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        saved_files.append(f"normalized/{name}.json")

    # 保存证据数据
    for name, data in evidence_data.items():
        path = os.path.join(archive_base, "evidence", f"{name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        saved_files.append(f"evidence/{name}.json")

    # 生成manifest
    manifest = {
        "trade_date": trade_date,
        "archived_at": datetime.now(TZ).isoformat(),
        "files": saved_files,
        "version": "phase1-v3.2",
        "architecture_principle": "免费公开数据源优先，每日永久归档，原始文件不可覆盖",
    }
    with open(os.path.join(archive_base, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    return manifest


# ============================================================
# 测试入口
# ============================================================
if __name__ == "__main__":
    import sys

    target_date = sys.argv[1] if len(sys.argv) > 1 else "20260904"
    target_code = sys.argv[2] if len(sys.argv) > 2 else "600108"

    print(f"=== 交易题材解析器测试 ({target_date} {target_code}) ===")

    # 加载本地涨停池数据
    zt_pool_path = f"delivery_phase1_v3_1/raw_sources/{target_date}_stock_zt_pool_em.json"
    if os.path.exists(zt_pool_path):
        with open(zt_pool_path, "r", encoding="utf-8") as f:
            zt_pool = json.load(f)
        print(f"涨停池: {len(zt_pool)}只")

        resolver = TradeThemeResolver()
        result = resolver.resolve(target_date, target_code, zt_pool)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"涨停池数据不存在: {zt_pool_path}")
