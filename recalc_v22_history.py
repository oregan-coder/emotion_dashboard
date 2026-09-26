# -*- coding: utf-8 -*-
"""
V2.2 历史快照批量重算脚本
遍历所有历史回放快照，重新计算V2.2周期状态识别器字段
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, '.')

from cycle_state_detector import detect_cycle_state

SNAPSHOT_DIR = Path('data/dashboards')

# 全局概念缓存（懒加载）
_CONCEPT_CACHE = None


def load_concept_cache():
    """加载概念缓存（懒加载）"""
    global _CONCEPT_CACHE
    if _CONCEPT_CACHE is None:
        cache_path = Path('data/concept_cache.json')
        if cache_path.exists():
            with open(cache_path, 'r', encoding='utf-8') as f:
                _CONCEPT_CACHE = json.load(f)
        else:
            _CONCEPT_CACHE = {}
    return _CONCEPT_CACHE


def build_theme_highest_board_map(snapshot: dict, date: str) -> dict:
    """
    构建题材→最高板数的映射表

    遍历当日所有涨停股（首板+二板+高标股），
    找到每个题材对应的最高连板数。

    返回: {题材名: 最高板数}
    """
    concept_cache = load_concept_cache()
    date_concepts = concept_cache.get(date, {})

    # 收集所有涨停股的代码和连板数
    all_limit_up = {}  # {code: board}

    # 首板股
    pool = snapshot.get('pool', {})
    for s in pool.get('first_board', []) or []:
        code = s.get('code', '')
        if code:
            all_limit_up[code] = 1

    # 二板股
    for s in pool.get('second_board', []) or []:
        code = s.get('code', '')
        if code:
            all_limit_up[code] = 2

    # 高标股（3板及以上）
    leader = snapshot.get('leader', {})
    for s in leader.get('high_boards', []) or []:
        code = s.get('code', '')
        board = int(s.get('board', 0) or 0)
        if code and board > 0:
            all_limit_up[code] = board

    # 最高标
    highest = leader.get('highest', {})
    if highest:
        code = highest.get('code', '')
        board = int(highest.get('board', 0) or 0)
        if code and board > 0:
            all_limit_up[code] = board

    # 构建题材→最高板映射
    theme_highest = {}
    theme_stocks = {}  # {concept: [code, ...]}
    stocks_with_concepts = 0
    stocks_without_concepts = 0
    for code, board in all_limit_up.items():
        concepts = date_concepts.get(code, [])
        if not concepts:
            # 如果概念缓存中没有，尝试从股票数据中获取
            stocks_without_concepts += 1
            continue
        stocks_with_concepts += 1
        for concept in concepts:
            if concept not in theme_highest or board > theme_highest[concept]:
                theme_highest[concept] = board
            if concept not in theme_stocks:
                theme_stocks[concept] = []
            theme_stocks[concept].append(code)

    # V2.3 Phase1 v3: 返回母体完整度信息
    universe_info = {
        "total_limit_up_stocks": len(all_limit_up),
        "stocks_with_concepts": stocks_with_concepts,
        "stocks_without_concepts": stocks_without_concepts,
        "concept_coverage_rate": (stocks_with_concepts / len(all_limit_up) * 100) if all_limit_up else 0,
        "universe_complete": stocks_without_concepts == 0,
        "concept_source": "concept_cache/F10概念缓存",
        "historical_validity_status": "UNVERIFIED_HISTORICAL",
    }

    return theme_highest, theme_stocks, universe_info


def extract_market_data(snapshot: dict) -> dict:
    """从快照中提取市场级别数据"""
    smash = snapshot.get('smash', {})
    limit = snapshot.get('limit', {})
    ladder = snapshot.get('ladder', [])

    # 最高板
    highest_board = int(smash.get('highest_board', 0) or 0)

    # 2→3成功率（从smash.rates中提取）
    rates = smash.get('rates', {}) or {}
    rate_23 = float(rates.get('rate23', 0) or rates.get('rate_23', 0) or
                     smash.get('rate23', 0) or smash.get('rate_23', 0) or 0)

    # 各板数量（从ladder中提取）
    board_counts = {}
    if isinstance(ladder, list):
        for item in ladder:
            board = int(item.get('board', 0) or 0)
            count = int(item.get('count', 0) or item.get('num', 0) or 0)
            if board > 0:
                board_counts[board] = count

    # 炸板率（从emotion_history.csv中获取，快照中未保存）
    open_board_rate = 0.0
    date_str = snapshot.get('date', '')
    try:
        import pandas as pd
        hist = pd.read_csv('data/emotion_history.csv', dtype={'date': str})
        row = hist[hist['date'] == str(date_str)]
        if not row.empty:
            open_board_rate = float(row.iloc[0].get('open_board_rate', 0) or 0)
    except Exception:
        pass

    # 二板股列表（用于核心二板检测）
    pool = snapshot.get('pool', {})
    second_board = pool.get('second_board', []) or []

    # 概念统计（简化版）
    concept_stats = {}
    for stock in second_board:
        concepts = stock.get('concepts', []) or [stock.get('top_concept', '')]
        for c in concepts:
            if c:
                concept_stats[c] = concept_stats.get(c, 0) + 1

    # 检测核心二板
    has_core_2board = detect_core_2board(second_board, concept_stats)

    return {
        "highest_board": highest_board,
        "board_4_count": board_counts.get(4, 0),
        "board_3_count": board_counts.get(3, 0),
        "board_3_plus_count": sum(v for k, v in board_counts.items() if k >= 3),
        "rate_23": rate_23,
        "open_board_rate": open_board_rate,
        "has_core_2board": has_core_2board,
        "second_board_stocks": second_board,
        "concept_stats": concept_stats,
    }


def detect_core_2board(second_boards: list, concept_stats: dict) -> bool:
    """检测是否存在核心二板"""
    if not second_boards or len(second_boards) > 3:
        return False

    # 概念排名
    sorted_concepts = sorted(concept_stats.items(), key=lambda x: -x[1])
    concept_rank = {c: i + 1 for i, (c, _) in enumerate(sorted_concepts)}

    # 封板资金前20%阈值
    all_amounts = sorted([s.get('seal_amount', 0) for s in second_boards], reverse=True)
    if not all_amounts:
        return False
    top20_idx = max(0, int(len(all_amounts) * 0.2) - 1)
    top20_threshold = all_amounts[top20_idx]

    for stock in second_boards:
        top_concept = stock.get('top_concept', '')
        rank = concept_rank.get(top_concept, 999)
        if rank > 3:
            continue
        if stock.get('seal_amount', 0) >= top20_threshold:
            return True

    return False


def extract_stock_data(stock: dict, all_second_boards: list, concept_stats: dict,
                       theme_highest_board_map: dict = None) -> dict:
    """从个股数据中提取V2.2种子股识别所需字段（V2.3修复版）"""
    top_concept = stock.get('top_concept', '')

    # V2.3：优先从theme模块获取统一题材排名（全市场涨停股排名）
    theme_rank = None
    modules = stock.get('modules', {})
    if isinstance(modules, dict):
        theme_module = modules.get('theme', {})
        if isinstance(theme_module, dict):
            details = theme_module.get('details', {})
            if isinstance(details, dict):
                rank_detail = details.get('板块涨停排名', {})
                if isinstance(rank_detail, dict):
                    theme_rank = rank_detail.get('raw')

    # 如果theme模块没有排名，回退到二板股概念统计（不精确，但有总比没有好）
    if theme_rank is None:
        sorted_concepts = sorted(concept_stats.items(), key=lambda x: -x[1])
        concept_rank_dict = {c: i + 1 for i, (c, _) in enumerate(sorted_concepts)}
        theme_rank = concept_rank_dict.get(top_concept, 999)

    # V2.3：真正计算题材最高板（B条件）
    # V2.3 Phase1 v3: 使用通用公式 stock_board_count == theme_max_board
    # 不再依赖"当前对象一定是二板"的假设
    is_theme_highest = False
    theme_highest_evidence = {
        "top_concept": top_concept,
        "stock_board_count": stock.get('board', 2),
        "theme_max_board": None,
        "formula": "is_theme_highest = (stock_board_count == theme_max_board)",
    }
    if theme_highest_board_map and top_concept:
        highest_board_in_theme = theme_highest_board_map.get(top_concept, 0)
        theme_highest_evidence["theme_max_board"] = highest_board_in_theme
        # 通用公式：当前股票板数 == 题材最高板数
        stock_board = int(stock.get('board', 2) or 2)
        if stock_board == highest_board_in_theme:
            is_theme_highest = True
    else:
        # 没有题材最高板映射时，保守设为False（不再硬编码True）
        is_theme_highest = False

    # 封板时间排名百分比（V2.3修复：缺失时给中性值50，不参与排序）
    valid_seal_times = [s.get('seal_time', '') for s in all_second_boards
                        if s.get('seal_time', '') and s.get('seal_time', '') not in ('235959', '000000', '999999')]
    stock_time = stock.get('seal_time', '')
    if valid_seal_times and stock_time and stock_time not in ('235959', '000000', '999999'):
        try:
            sorted_times = sorted(valid_seal_times)
            time_rank = sorted_times.index(stock_time) + 1
            seal_time_rank_pct = round(time_rank / len(sorted_times) * 100, 1)
        except (ValueError, ZeroDivisionError):
            seal_time_rank_pct = 50.0
    else:
        # 封板时间缺失，设为None（让种子股识别标记为数据缺失）
        seal_time_rank_pct = None

    # 封板资金排名百分比（V2.3修复：缺失时给中性值50）
    valid_amounts = [s.get('seal_amount', 0) for s in all_second_boards
                      if s.get('seal_amount', 0) and float(s.get('seal_amount', 0)) >= 1000]
    stock_amount = stock.get('seal_amount', 0)
    if valid_amounts and stock_amount and float(stock_amount) >= 1000:
        try:
            sorted_amounts = sorted(valid_amounts, reverse=True)
            amount_rank = sorted_amounts.index(stock_amount) + 1
            seal_amount_rank_pct = round(amount_rank / len(sorted_amounts) * 100, 1)
        except (ValueError, ZeroDivisionError):
            seal_amount_rank_pct = None
    else:
        # 封板资金缺失，设为None
        seal_amount_rank_pct = None

    # 是否非尾盘板（14:00以前）——V2.3修复：缺失时为False，但标记为数据缺失
    seal_time = stock.get('seal_time', '')
    is_not_late_seal = False
    if seal_time and len(seal_time) >= 4 and seal_time not in ('235959', '000000', '999999'):
        try:
            hour = int(seal_time[:2])
            minute = int(seal_time[2:4])
            is_not_late_seal = hour < 14 or (hour == 14 and minute == 0)
        except (ValueError, IndexError):
            pass

    return {
        "code": stock.get('code', ''),
        "name": stock.get('name', ''),
        "board": 2,
        "top_concept": top_concept,
        "theme_rank": theme_rank,
        "is_theme_highest": is_theme_highest,
        "theme_highest_evidence": theme_highest_evidence,
        "seal_time": seal_time,
        "seal_time_rank_pct": seal_time_rank_pct,
        "seal_amount": stock_amount,
        "seal_amount_rank_pct": seal_amount_rank_pct,
        "is_not_late_seal": is_not_late_seal,
    }


def process_snapshot(snapshot_path: Path) -> bool:
    """处理单个快照"""
    try:
        with open(snapshot_path, 'r', encoding='utf-8') as f:
            snapshot = json.load(f)

        # 提取市场数据
        market_data = extract_market_data(snapshot)

        # 获取二板股列表
        pool = snapshot.get('pool', {})
        tomorrow = pool.get('tomorrow', []) or []
        second_board = pool.get('second_board', []) or []

        if not tomorrow:
            print(f"  {snapshot_path.stem}: 无三板预案，跳过")
            return False

        # 市场环境评分（从第一只股票的modules中获取）
        market_score = 0.0
        if tomorrow and tomorrow[0].get('modules'):
            market_score = float(tomorrow[0]['modules'].get('market', {}).get('total', 0) or 0)

        # V2.3：构建题材最高板映射表（用于B条件判定）
        # V2.3 Phase1 v3: 返回3个值（theme_highest, theme_stocks, universe_info）
        date_str = snapshot_path.stem
        theme_highest_board_map, theme_stocks_map, theme_universe_info = build_theme_highest_board_map(snapshot, date_str)

        # 对每只股票计算V2.2
        updated_count = 0
        for stock in tomorrow:
            grade = stock.get('grade', 'C')
            stock_data = extract_stock_data(
                stock,
                second_board or tomorrow,
                market_data.get('concept_stats', {}),
                theme_highest_board_map
            )

            v22_result = detect_cycle_state(
                market_data=market_data,
                stock=stock_data,
                rating=grade,
                market_score=market_score
            )

            stock['v22'] = v22_result
            stock['model_version'] = 'V2.2'
            updated_count += 1

        # 保存更新后的快照
        with open(snapshot_path, 'w', encoding='utf-8') as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)

        print(f"  {snapshot_path.stem}: 更新{updated_count}只股票 V2.2字段 "
              f"(市场状态:{market_data.get('highest_board', 0)}板 "
              f"2→3:{market_data.get('rate_23', 0):.1f}% "
              f"炸板:{market_data.get('open_board_rate', 0):.1f}%)")
        return True

    except Exception as e:
        print(f"  {snapshot_path.stem}: 处理失败 - {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("=" * 60)
    print("V2.2 历史快照批量重算")
    print("=" * 60)

    snapshots = sorted(SNAPSHOT_DIR.glob('*.json'))
    print(f"\n找到 {len(snapshots)} 个历史快照")

    success_count = 0
    fail_count = 0
    skip_count = 0

    for i, snapshot_path in enumerate(snapshots, 1):
        print(f"\n[{i}/{len(snapshots)}] 处理 {snapshot_path.stem}...")
        result = process_snapshot(snapshot_path)
        if result is True:
            success_count += 1
        elif result is False:
            skip_count += 1
        else:
            fail_count += 1

    print("\n" + "=" * 60)
    print(f"处理完成：成功 {success_count}，跳过 {skip_count}，失败 {fail_count}")
    print("=" * 60)


if __name__ == '__main__':
    main()
