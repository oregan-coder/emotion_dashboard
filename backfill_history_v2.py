# -*- coding: utf-8 -*-
"""
============================================================
A股打板情绪仪表盘 V3.2
历史数据回填脚本 V2（新浪源版）

功能：
  通过新浪财经接口获取全A股历史行情，本地计算涨停股/连板数，
  突破akshare东方财富涨停池仅支持最近30个交易日的限制。
  可获取最近3个月以上的历史数据。

技术方案：
  1. stock_zh_a_spot（新浪源）获取全A股代码+名称（约21秒）
  2. stock_zh_a_daily（新浪源）多线程获取每只股票历史行情
  3. 本地计算涨跌幅、筛选涨停股、回溯连板数
  4. 调用现有 calculate_smash / calculate_emotion 计算情绪指标
  5. 写入 emotion_history.csv / smash_history.csv / 生成回放快照

用法：
  py -3.13 -X utf8 backfill_history_v2.py
  py -3.13 -X utf8 backfill_history_v2.py --days 90
  py -3.13 -X utf8 backfill_history_v2.py --start 20260601 --end 20260904
  py -3.13 -X utf8 backfill_history_v2.py --workers 10
  py -3.13 -X utf8 backfill_history_v2.py --use-cache  # 使用已缓存的行情数据

说明：
  - 首次运行需下载全A股历史行情，10线程约20-30分钟
  - 下载的行情数据缓存到 data/cache/ 目录，后续运行可直接使用
  - 涨停判断：主板≥9.9%，创业板/科创板≥19.9%
  - 连板数：从目标日期向前回溯连续涨停天数
  - 炸板数据无法从日线获取，砸盘情绪核心依赖晋级率（不受影响）
============================================================
"""

import argparse
import time
import sys
import os
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

# 项目根目录
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from smash_engine import calculate_smash
from emotion_engine import calculate_emotion
from cycle_engine import analyze_cycle
from position_engine import calculate_position
from history_manager import save_history, load_history
from dashboard_snapshot import save_dashboard_snapshot
from config import SMASH_HISTORY_FILE, SMASH_HISTORY_COLUMNS

# 缓存目录
CACHE_DIR = PROJECT_ROOT / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 全A股行情缓存文件（用pickle，Python原生支持，无需额外库）
ALL_STOCK_HIST_CACHE = CACHE_DIR / "all_stock_hist.pkl"
STOCK_LIST_CACHE = CACHE_DIR / "stock_list.csv"


# ============================================================
# 股票列表获取
# ============================================================

def get_stock_list(use_cache=True):
    """获取全A股代码和名称列表"""
    if use_cache and STOCK_LIST_CACHE.exists():
        print(f"  从缓存读取股票列表: {STOCK_LIST_CACHE}")
        df = pd.read_csv(STOCK_LIST_CACHE, dtype={"code": str})
        return df

    print("  从新浪财经获取全A股列表...", end=" ", flush=True)
    import akshare as ak
    start = time.time()
    df = ak.stock_zh_a_spot()
    elapsed = time.time() - start
    print(f"✓ {len(df)} 只, 耗时 {elapsed:.1f}s")

    # 标准化列名
    code_col = next((c for c in df.columns if "代码" in str(c)), df.columns[0])
    name_col = next((c for c in df.columns if "名称" in str(c)), df.columns[1])
    result = pd.DataFrame({
        "code": df[code_col].astype(str).str.extract(r"(\d{6})")[0].fillna(""),
        "name": df[name_col].astype(str)
    })
    result = result[result["code"] != ""].drop_duplicates(subset=["code"]).reset_index(drop=True)

    # 缓存
    result.to_csv(STOCK_LIST_CACHE, index=False, encoding="utf-8-sig")
    print(f"  股票列表已缓存: {STOCK_LIST_CACHE}")
    return result


def filter_stock_list(df):
    """过滤股票范围：主板/创业板/科创板，剔除ST/北交所"""
    mask = df["code"].str.startswith((
        "000", "001", "002", "003",  # 深市主板
        "300",                         # 创业板
        "600", "601", "603", "605",   # 沪市主板
        "688"                          # 科创板
    ))
    # 剔除ST
    mask &= ~df["name"].astype(str).str.contains("ST", case=False, na=False)
    result = df[mask].reset_index(drop=True)
    return result


def code_to_sina_symbol(code):
    """转换股票代码为新浪格式：sz000001 / sh600000"""
    if code.startswith(("0", "3")):
        return f"sz{code}"
    else:
        return f"sh{code}"


def get_limit_threshold(code):
    """获取涨停阈值：主板9.9%，创业板/科创板19.9%"""
    if code.startswith(("300", "688")):
        return 19.9
    return 9.9


# ============================================================
# 历史行情获取（baostock单线程，比新浪源快5倍）
# ============================================================

def code_to_baostock_symbol(code):
    """转换股票代码为baostock格式：sz.000001 / sh.600000"""
    if code.startswith(("0", "3")):
        return f"sz.{code}"
    else:
        return f"sh.{code}"


def fetch_all_stock_hist(stock_df, start_date, end_date, workers=1, use_cache=True):
    """
    单线程获取全A股历史行情（baostock数据源）

    baostock单线程约0.45秒/只，4500只约34分钟。
    多线程不稳定（服务器端连接限制），故用单线程。
    """
    import baostock as bs

    if use_cache and ALL_STOCK_HIST_CACHE.exists():
        print(f"  从缓存读取全A股行情: {ALL_STOCK_HIST_CACHE}")
        df = pd.read_pickle(ALL_STOCK_HIST_CACHE)
        print(f"  缓存数据: {len(df)} 行, {df['code'].nunique()} 只股票")
        return df

    symbols = [code_to_baostock_symbol(code) for code in stock_df["code"]]
    total = len(symbols)
    print(f"\n  开始baostock单线程获取历史行情: {total} 只股票")
    print(f"  日期范围: {start_date} ~ {end_date}")
    print(f"  预计耗时: 约 {total * 0.45 / 60:.1f} 分钟")

    # 登录baostock
    lg = bs.login()
    if lg.error_code != '0':
        print(f"  ✗ baostock登录失败: {lg.error_msg}")
        return pd.DataFrame()
    print(f"  baostock登录成功")

    all_data = []
    success_count = 0
    fail_count = 0
    start_time = time.time()

    fields = "date,code,open,high,low,close,volume,amount,turn,pctChg"

    for i, symbol in enumerate(symbols, 1):
        try:
            rs = bs.query_history_k_data_plus(
                symbol, fields,
                start_date=start_date, end_date=end_date,
                frequency="d", adjustflag="2"
            )
            data_list = []
            while (rs.error_code == '0') and rs.next():
                data_list.append(rs.get_row_data())

            if data_list:
                df_stock = pd.DataFrame(data_list, columns=fields.split(","))
                # 转换数值列
                for col in ["open", "high", "low", "close", "volume", "amount", "turn", "pctChg"]:
                    df_stock[col] = pd.to_numeric(df_stock[col], errors="coerce")
                df_stock["code"] = symbol.split(".")[1]  # 去掉sz./sh.前缀
                all_data.append(df_stock)
                success_count += 1
            else:
                fail_count += 1
        except Exception:
            fail_count += 1

        if i % 200 == 0 or i == total:
            elapsed = time.time() - start_time
            rate = i / elapsed
            eta = (total - i) / rate / 60
            print(f"  进度: {i}/{total} ({i/total*100:.1f}%) "
                  f"成功:{success_count} 失败:{fail_count} "
                  f"速度:{rate:.1f}只/s 预计剩余:{eta:.1f}分钟")

    # 登出
    bs.logout()

    if not all_data:
        print("  ✗ 未获取到任何行情数据")
        return pd.DataFrame()

    result = pd.concat(all_data, ignore_index=True)
    print(f"\n  获取完成: 成功 {success_count} 只, 失败 {fail_count} 只")
    print(f"  总数据量: {len(result)} 行")

    # 缓存
    print(f"  缓存全A股行情到: {ALL_STOCK_HIST_CACHE}")
    try:
        result.to_pickle(ALL_STOCK_HIST_CACHE)
        print(f"  缓存完成")
    except Exception as cache_err:
        print(f"  ⚠ 缓存失败（不影响后续计算）: {cache_err}")

    return result


# ============================================================
# 本地计算涨停股和连板数
# ============================================================

def calc_daily_pct(df):
    """统一涨跌幅列名（baostock返回pctChg，统一为pct）"""
    df = df.sort_values(["code", "date"]).copy()
    if "pctChg" in df.columns and "pct" not in df.columns:
        df["pct"] = df["pctChg"]
    elif "pct" not in df.columns:
        # 新浪源没有pct列，自己计算
        df["pct"] = df.groupby("code")["close"].pct_change() * 100
    return df


def build_limit_up_pool(hist_df, stock_names, target_date):
    """
    构建指定日期的涨停池

    返回DataFrame，包含：代码、名称、连板数、涨跌幅
    """
    # 筛选目标日期及之前的数据（用于回溯连板数）
    df = hist_df[hist_df["date"] <= target_date].copy()

    # 按股票和日期排序
    df = df.sort_values(["code", "date"])

    # 计算每只股票每天是否涨停
    df["threshold"] = df["code"].map(get_limit_threshold)
    df["is_limit"] = df["pct"] >= df["threshold"] * 0.99  # 留0.01的容差

    # 筛选目标日期涨停的股票
    today = df[df["date"] == target_date]
    today_limit = today[today["is_limit"]].copy()

    if today_limit.empty:
        return pd.DataFrame(columns=["代码", "名称", "连板数", "涨跌幅"])

    # 回溯每只股票的连板数
    def calc_consecutive_boards(code):
        stock_data = df[df["code"] == code].sort_values("date", ascending=False)
        count = 0
        for _, row in stock_data.iterrows():
            if row["is_limit"]:
                count += 1
            else:
                break
        return count

    today_limit["连板数"] = today_limit["code"].map(calc_consecutive_boards)
    today_limit["名称"] = today_limit["code"].map(stock_names)
    today_limit["涨跌幅"] = today_limit["pct"].round(2)

    # V2.3 Phase1 v3: 保留完整日线字段，不得只保留4列
    # 字段来源：BaoStock/新浪日线（hist_df本身已包含这些字段）
    # "股票名单取得成功"和"评分字段取得完整"是两个不同状态
    result_columns = ["code", "名称", "连板数", "涨跌幅"]
    rename_map = {"code": "代码"}

    # 保留OHLC
    for col in ["open", "high", "low", "close"]:
        if col in today_limit.columns:
            result_columns.append(col)
            rename_map[col] = col

    # 保留成交股数（volume单位：股）
    if "volume" in today_limit.columns:
        result_columns.append("volume")
        rename_map["volume"] = "volume_shares"

    # 保留成交额（amount单位：元）
    if "amount" in today_limit.columns:
        result_columns.append("amount")
        rename_map["amount"] = "amount_cny"

    # 保留换手率
    if "turn" in today_limit.columns:
        result_columns.append("turn")
        rename_map["turn"] = "turnover_pct"

    result = today_limit[result_columns].rename(columns=rename_map)
    result = result.sort_values("连板数", ascending=False).reset_index(drop=True)

    # 数据质量标记
    result["data_status"] = "PARTIAL"  # 名单成功但封板时间/资金等字段可能不完整
    result["field_sources"] = result.apply(
        lambda r: json.dumps({
            "code": "hist_df", "名称": "stock_names", "连板数": "local_calc",
            "涨跌幅": "hist_df.pct", "open": "hist_df", "high": "hist_df",
            "low": "hist_df", "close": "hist_df", "volume_shares": "hist_df.volume(单位:股)",
            "amount_cny": "hist_df.amount(单位:元)", "turnover_pct": "hist_df.turn",
            "first_seal_time": "MISSING(日线无此字段)", "close_seal_amount_cny": "MISSING(日线无此字段)",
            "open_break_count": "MISSING(日线无此字段)",
        }, ensure_ascii=False), axis=1
    )

    return result


def build_limit_down_pool(hist_df, stock_names, target_date):
    """构建指定日期的跌停池"""
    df = hist_df[hist_df["date"] == target_date].copy()
    if df.empty:
        return pd.DataFrame(columns=["代码", "名称", "涨跌幅"])

    # 跌停阈值：主板-9.9%，创业板/科创板-19.9%
    df["threshold"] = df["code"].map(get_limit_threshold)
    df["is_limit_down"] = df["pct"] <= -df["threshold"] * 0.99

    today_limit_down = df[df["is_limit_down"]].copy()
    if today_limit_down.empty:
        return pd.DataFrame(columns=["代码", "名称", "涨跌幅"])

    today_limit_down["名称"] = today_limit_down["code"].map(stock_names)
    today_limit_down["涨跌幅"] = today_limit_down["pct"].round(2)

    result = today_limit_down[["code", "名称", "涨跌幅"]].rename(
        columns={"code": "代码"}
    ).reset_index(drop=True)

    return result


# ============================================================
# 砸盘历史CSV读写
# ============================================================

def load_smash_history_df():
    path = Path(SMASH_HISTORY_FILE)
    if not path.exists():
        return pd.DataFrame(columns=SMASH_HISTORY_COLUMNS)
    try:
        df = pd.read_csv(path, dtype={"date": str})
    except Exception:
        return pd.DataFrame(columns=SMASH_HISTORY_COLUMNS)
    for col in SMASH_HISTORY_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[SMASH_HISTORY_COLUMNS]


def save_smash_record(record):
    df = load_smash_history_df()
    if not df.empty:
        df = df[df["date"].astype(str) != str(record["date"])]
    new_row = pd.DataFrame([record])
    for col in SMASH_HISTORY_COLUMNS:
        if col not in new_row.columns:
            new_row[col] = ""
    new_row = new_row[SMASH_HISTORY_COLUMNS]
    result = pd.concat([df, new_row], ignore_index=True)
    result = result.sort_values(by="date").reset_index(drop=True)
    Path(SMASH_HISTORY_FILE).parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(SMASH_HISTORY_FILE, index=False, encoding="utf-8-sig")


# ============================================================
# 交易日处理
# ============================================================

def get_trade_dates_from_hist(hist_df, start_date, end_date):
    """从历史行情数据中提取交易日列表"""
    dates = sorted(hist_df["date"].unique())
    dates = [d for d in dates if start_date <= d <= end_date]
    return dates


# ============================================================
# 单日数据处理
# ============================================================

class SimpleDashboardData:
    """简化版DashboardData，用于传入calculate_smash"""
    def __init__(self, date, previous_date, limit_up, previous_limit_up, limit_down, open_board=None):
        self.date = date
        self.previous_date = previous_date
        self.limit_up = limit_up
        self.previous_limit_up = previous_limit_up
        self.limit_down = limit_down
        self.open_board = open_board
        self.market = pd.DataFrame()
        self.previous_pool_performance = pd.DataFrame()


def process_one_date_v2(hist_df, stock_names, target_date, previous_date):
    """处理单个交易日（V2新浪源版）"""
    # 构建涨停池
    limit_up = build_limit_up_pool(hist_df, stock_names, target_date)
    previous_limit_up = build_limit_up_pool(hist_df, stock_names, previous_date)
    limit_down = build_limit_down_pool(hist_df, stock_names, target_date)

    if limit_up.empty:
        return "no_data", None

    # 计算砸盘情绪
    smash = calculate_smash(limit_up, previous_limit_up, open_board=None)

    # 计算情绪分
    emotion = calculate_emotion(
        limit_up_count=len(limit_up),
        highest_board=smash.highest_board,
        rate12=smash.rate12,
        yesterday_rate=0,
        break_rate=smash.break_rate,
        high_loss_count=smash.high_loss_count,
        up_count=0,
        down_count=0
    )

    # 转换日期格式为YYYYMMDD（与原有CSV格式一致）
    date_compact = target_date.replace("-", "")

    # 构建数据对象
    data = SimpleDashboardData(
        date=date_compact,
        previous_date=previous_date.replace("-", ""),
        limit_up=limit_up,
        previous_limit_up=previous_limit_up,
        limit_down=limit_down,
        open_board=pd.DataFrame()
    )

    # 写入emotion_history
    history_record = {
        "date": date_compact,
        "emotion_score": emotion.score,
        "limit_up_count": len(limit_up),
        "limit_down_count": len(limit_down),
        "open_board_count": 0,
        "open_board_rate": smash.break_rate,
        "highest_board": smash.highest_board,
        "rate_12": smash.rate12,
        "rate_23": smash.rate23,
        "break_rate": smash.break_rate,
        "cycle_stage": "",
        "height_stage": ""
    }
    save_history(history_record)

    # 写入smash_history
    smash_record = {
        "date": date_compact,
        "smash_score": smash.score,
        "highest_board": smash.highest_board,
        "highest_stock": smash.highest_stock,
        "rate_23": smash.rate23,
        "rate_34": smash.rate34,
        "rate_45": smash.rate45,
        "rate_56": smash.rate56,
    }
    save_smash_record(smash_record)

    # 生成dashboard快照
    try:
        hist = load_history()
        cycle = analyze_cycle(hist, emotion.score, smash.highest_board)
        position = calculate_position(cycle, smash, emotion)
        save_dashboard_snapshot(
            data, smash, emotion, cycle, position,
            archive_only=True
        )
    except Exception as snap_err:
        print(f"    (快照生成失败: {snap_err})", end=" ", flush=True)

    print(f"✓ 情绪分={emotion.score:.2f} 砸盘={smash.score:.2f} "
          f"最高板={smash.highest_board}({smash.highest_stock}) "
          f"涨停={len(limit_up)} 跌停={len(limit_down)}")

    return "success", smash


# ============================================================
# 主函数
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="A股情绪仪表盘历史数据回填 V2（新浪源版）")
    parser.add_argument("--days", type=int, default=90, help="回填最近N个自然日（默认90）")
    parser.add_argument("--start", type=str, default="", help="开始日期 YYYYMMDD")
    parser.add_argument("--end", type=str, default="", help="结束日期 YYYYMMDD")
    parser.add_argument("--workers", type=int, default=1, help="线程数量（baostock建议单线程，默认1）")
    parser.add_argument("--use-cache", action="store_true", help="使用已缓存的行情数据")
    parser.add_argument("--force", action="store_true", help="强制重新计算（覆盖已存在的日期）")
    args = parser.parse_args()

    print("=" * 60)
    print("  A股情绪仪表盘 V3.2 - 历史数据回填 V2（新浪源版）")
    print("=" * 60)

    # 确定日期范围
    if args.start and args.end:
        start_date = args.start
        end_date = args.end
    else:
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=args.days)).strftime("%Y%m%d")

    # 转换为新浪格式（带横杠）
    start_date_sina = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
    end_date_sina = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"

    print(f"\n日期范围: {start_date} ~ {end_date}")
    print(f"线程数量: {args.workers}")
    print(f"使用缓存: {args.use_cache}")

    # 步骤1：获取股票列表
    print("\n" + "=" * 60)
    print("  步骤1: 获取全A股列表")
    print("=" * 60)
    stock_df = get_stock_list(use_cache=True)
    stock_df = filter_stock_list(stock_df)
    print(f"  过滤后: {len(stock_df)} 只股票（主板+创业板+科创板，剔除ST）")

    # 股票名称映射
    stock_names = dict(zip(stock_df["code"], stock_df["name"]))

    # 步骤2：获取全A股历史行情
    print("\n" + "=" * 60)
    print("  步骤2: 获取全A股历史行情")
    print("=" * 60)
    # 多获取15天数据用于计算连板数
    fetch_start = (datetime.strptime(start_date, "%Y%m%d") - timedelta(days=20)).strftime("%Y%m%d")
    fetch_start_sina = f"{fetch_start[:4]}-{fetch_start[4:6]}-{fetch_start[6:8]}"

    hist_df = fetch_all_stock_hist(
        stock_df, fetch_start_sina, end_date_sina,
        workers=args.workers, use_cache=args.use_cache
    )

    if hist_df.empty:
        print("  ✗ 未获取到行情数据，退出")
        sys.exit(1)

    # 计算涨跌幅
    print("\n  计算每日涨跌幅...", end=" ", flush=True)
    hist_df = calc_daily_pct(hist_df)
    print(f"✓ 共 {len(hist_df)} 条记录")

    # 步骤3：获取交易日列表
    print("\n" + "=" * 60)
    print("  步骤3: 确定交易日列表")
    print("=" * 60)
    trade_dates = get_trade_dates_from_hist(hist_df, start_date_sina, end_date_sina)
    print(f"  交易日数量: {len(trade_dates)} 天")
    if trade_dates:
        print(f"  范围: {trade_dates[0]} ~ {trade_dates[-1]}")

    # 步骤4：过滤已存在的日期
    if not args.force:
        try:
            existing_df = load_history()
            existing = set(existing_df["date"].astype(str).tolist()) if not existing_df.empty else set()
        except Exception:
            existing = set()
        # 转换日期格式匹配
        existing_sina = {f"{d[:4]}-{d[4:6]}-{d[6:8]}" for d in existing}
        to_process = [d for d in trade_dates if d not in existing_sina]
        skipped = len(trade_dates) - len(to_process)
        print(f"  已存在: {skipped} 天（自动跳过）")
    else:
        to_process = trade_dates
        print(f"  强制模式: 覆盖全部 {len(to_process)} 天")

    print(f"  待处理: {len(to_process)} 天")

    if not to_process:
        print("\n所有日期均已存在，无需回填")
        return

    # 步骤5：逐日处理
    print("\n" + "=" * 60)
    print("  步骤4: 逐日计算情绪指标并写入CSV")
    print("=" * 60)

    success_count = 0
    no_data_count = 0
    fail_count = 0

    for i, target_date in enumerate(to_process, 1):
        # 找前一个交易日
        date_idx = trade_dates.index(target_date)
        previous_date = trade_dates[date_idx - 1] if date_idx > 0 else target_date

        print(f"[{i}/{len(to_process)}] {target_date} (前一交易日:{previous_date}) ", end="", flush=True)

        try:
            result, _ = process_one_date_v2(hist_df, stock_names, target_date, previous_date)
            if result == "success":
                success_count += 1
            elif result == "no_data":
                no_data_count += 1
                print("⚠ 无涨停数据，跳过")
            else:
                fail_count += 1
        except Exception as e:
            fail_count += 1
            print(f"✗ 失败: {e}")

    # 完成
    print("\n" + "=" * 60)
    print(f"  回填完成！成功: {success_count} 天, 无数据: {no_data_count} 天, 失败: {fail_count} 天")
    print(f"  emotion_history.csv 和 smash_history.csv 已更新")
    print(f"  回放快照已生成到 data/dashboards/")
    print("=" * 60)


if __name__ == "__main__":
    main()
