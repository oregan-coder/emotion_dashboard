# -*- coding: utf-8 -*-
"""
V2.3 历史数据填充脚本
1. 从baostock缓存填充成交量、成交额、换手率（全部64天）
2. 从akshare填充最近13天的封板时间、封板资金
3. 更早日期的封板时间/资金保持为空（真实无法获取）
"""
import json
import pickle
import pandas as pd
import akshare as ak
from pathlib import Path
from datetime import datetime

dashboard_dir = Path('data/dashboards')

# ============================================================
# 1. 加载baostock缓存
# ============================================================
print("=== 加载baostock缓存 ===")
with open('data/cache/all_stock_hist.pkl', 'rb') as f:
    baostock_df = pickle.load(f)

print(f"缓存记录数: {len(baostock_df)}")
print(f"列名: {list(baostock_df.columns)}")

# 转换code格式：baostock是 sh.600000 / sz.000001，快照是 600000 / 000001
def convert_baostock_code(code):
    """把 sh.600000 转为 600000"""
    if '.' in code:
        return code.split('.')[1]
    return code

baostock_df['code_clean'] = baostock_df['code'].apply(convert_baostock_code)
# 转换date格式：2026-09-04 -> 20260904
baostock_df['date_clean'] = baostock_df['date'].str.replace('-', '')

# 创建查找索引
baostock_lookup = {}
for _, row in baostock_df.iterrows():
    key = (row['date_clean'], row['code_clean'])
    baostock_lookup[key] = {
        'volume': row.get('volume', 0),
        'amount': row.get('amount', 0),
        'turn': row.get('turn', 0),
        'pctChg': row.get('pctChg', 0),
    }

print(f"查找索引构建完成: {len(baostock_lookup)}条")

# ============================================================
# 2. 从akshare获取最近13天的涨停池数据（封板时间、封板资金）
# ============================================================
print("\n=== 从akshare获取涨停池数据 ===")

# 获取所有快照日期
snapshot_dates = sorted([f.stem for f in dashboard_dir.glob('*.json')])
print(f"快照日期范围: {snapshot_dates[0]} ~ {snapshot_dates[-1]}")

# 尝试获取每个日期的涨停池数据
akshare_zt_data = {}  # {date: {code: {seal_time, seal_amount, ...}}}
akshare_success_dates = []
akshare_fail_dates = []

for date in snapshot_dates:
    try:
        df = ak.stock_zt_pool_em(date=date)
        if df is not None and len(df) > 0:
            stock_dict = {}
            for _, row in df.iterrows():
                code = str(row.get('代码', '')).zfill(6)
                seal_time = str(row.get('首次封板时间', '')).strip()
                # 确保封板时间是6位数字
                if seal_time and len(seal_time) == 6 and seal_time.isdigit():
                    pass
                else:
                    seal_time = ''
                seal_amount = float(row.get('封板资金', 0) or 0)
                turnover = float(row.get('换手率', 0) or 0)
                stock_dict[code] = {
                    'seal_time': seal_time,
                    'seal_amount': seal_amount,
                    'turnover_akshare': turnover,
                    'name': row.get('名称', ''),
                }
            akshare_zt_data[date] = stock_dict
            akshare_success_dates.append(date)
            print(f"✅ {date}: {len(stock_dict)}只涨停股")
        else:
            akshare_fail_dates.append(date)
            print(f"❌ {date}: 空数据（超出akshare范围）")
    except Exception as e:
        akshare_fail_dates.append(date)
        print(f"❌ {date}: {str(e)[:80]}")

print(f"\nakshare成功获取: {len(akshare_success_dates)}天")
print(f"akshare无法获取: {len(akshare_fail_dates)}天")
if akshare_success_dates:
    print(f"akshare覆盖范围: {akshare_success_dates[0]} ~ {akshare_success_dates[-1]}")

# ============================================================
# 3. 填充所有快照
# ============================================================
print("\n=== 开始填充快照 ===")

total_baostock_filled = 0
total_akshare_filled = 0
total_stocks = 0

for f in sorted(dashboard_dir.glob('*.json')):
    date = f.stem
    with open(f, 'r', encoding='utf-8') as fp:
        snapshot = json.load(fp)

    pool = snapshot.get('pool', {})
    changed = False

    # 填充三板预案
    for stock in pool.get('tomorrow', []):
        total_stocks += 1
        code = stock.get('code', '')

        # 从baostock填充成交量、成交额、换手率
        key = (date, code)
        if key in baostock_lookup:
            bd = baostock_lookup[key]
            # 只在原值为0或空时填充
            if not stock.get('volume') or float(stock.get('volume', 0) or 0) == 0:
                stock['volume'] = bd['volume']
                total_baostock_filled += 1
                changed = True
            if not stock.get('turnover') or float(stock.get('turnover', 0) or 0) == 0:
                stock['turnover'] = bd['turn']
                total_baostock_filled += 1
                changed = True
            # amount字段可能叫volume或amount
            if 'amount' not in stock or not stock.get('amount'):
                stock['amount'] = bd['amount']
                total_baostock_filled += 1
                changed = True

        # 从akshare填充封板时间、封板资金
        if date in akshare_zt_data and code in akshare_zt_data[date]:
            ad = akshare_zt_data[date][code]
            # 封板时间：只在原值为空时填充
            if not stock.get('seal_time') and ad['seal_time']:
                stock['seal_time'] = ad['seal_time']
                stock['seal_time_fmt'] = f"{ad['seal_time'][:2]}:{ad['seal_time'][2:4]}"
                total_akshare_filled += 1
                changed = True
            # 封板资金：只在原值为0时填充
            if (not stock.get('seal_amount') or float(stock.get('seal_amount', 0) or 0) == 0) and ad['seal_amount'] > 0:
                stock['seal_amount'] = ad['seal_amount']
                total_akshare_filled += 1
                changed = True

    # 填充二板股
    for stock in pool.get('second_board', []):
        total_stocks += 1
        code = stock.get('code', '')

        key = (date, code)
        if key in baostock_lookup:
            bd = baostock_lookup[key]
            if not stock.get('volume') or float(stock.get('volume', 0) or 0) == 0:
                stock['volume'] = bd['volume']
                total_baostock_filled += 1
                changed = True
            if not stock.get('turnover') or float(stock.get('turnover', 0) or 0) == 0:
                stock['turnover'] = bd['turn']
                total_baostock_filled += 1
                changed = True

        if date in akshare_zt_data and code in akshare_zt_data[date]:
            ad = akshare_zt_data[date][code]
            if not stock.get('seal_time') and ad['seal_time']:
                stock['seal_time'] = ad['seal_time']
                total_akshare_filled += 1
                changed = True
            if (not stock.get('seal_amount') or float(stock.get('seal_amount', 0) or 0) == 0) and ad['seal_amount'] > 0:
                stock['seal_amount'] = ad['seal_amount']
                total_akshare_filled += 1
                changed = True

    if changed:
        with open(f, 'w', encoding='utf-8') as fp:
            json.dump(snapshot, fp, ensure_ascii=False, indent=2)

print(f"\n=== 填充完成 ===")
print(f"总股票数: {total_stocks}")
print(f"baostock填充字段数: {total_baostock_filled}")
print(f"akshare填充字段数: {total_akshare_filled}")
print(f"akshare无法覆盖的日期: {akshare_fail_dates}")
