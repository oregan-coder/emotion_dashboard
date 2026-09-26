# -*- coding: utf-8 -*-
"""
5535 热库日志清理脚本（只清 s02a/s02b 运行日志，不动业务数据）

保留策略：
- s02a_jobs / s02a_steps / s02a_integrity：保留"进行中"(finished_at IS NULL) + 最近 N 天（默认3天）
- s02a_profiles：保留最近 N 天（默认3天）
- s02b_revisions：保留 head 指向的 + 最近 M 天（默认7天）创建的；其余删除
- s02b_revisions_fact：随 s02b_revisions 同步删除
- 证据库：清理不再被热库引用的孤立 blob

用法：
  F:\\Python3.13\\python.exe -S tools\\cleanup_logs.py [--days 3] [--rev-days 7] [--no-vacuum] [--dry-run]

安全：
- 执行前自动做一致性备份到 .5535_backups\*_pre_logclean.sqlite3
- --dry-run 只统计不删除
- 只删 s02a/s02b 日志表，不触碰 published_days/batches_fact/snapshot 等业务表
"""
from __future__ import annotations
import sqlite3, pathlib, datetime, sys, argparse, time

PROJECT = pathlib.Path(r'F:\PythonProject\emotion_dashboard')
HOT = PROJECT / 'data' / '.migration_shadow' / 'market_store_5535.next.sqlite3'
EVIDENCE = PROJECT / 'data' / '.migration_shadow' / 'evidence_5535.next.sqlite3'
BACKUP_DIR = PROJECT / '.5535_backups'

def now_str(): return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def connect_plain(path):
    """绕过 shim 直连（用 -S 运行或直接 sqlite3.connect 均可）"""
    return sqlite3.connect(str(path), timeout=30)

def backup():
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    BACKUP_DIR.mkdir(exist_ok=True)
    made = []
    for src, tag in [(HOT, 'hot'), (EVIDENCE, 'ev')]:
        dst = BACKUP_DIR / f'{tag}_{stamp}_pre_logclean.sqlite3'
        s = sqlite3.connect(str(src))
        d = sqlite3.connect(str(dst))
        try:
            with d:
                s.backup(d)
        finally:
            d.close(); s.close()
        made.append((dst, dst.stat().st_size / 1048576))
    return made

def analyze_hot(conn, s02a_days, s02b_days):
    c = conn.cursor()
    cut_a = (time.time() - s02a_days * 86400)
    cut_b_iso = (datetime.datetime.now() - datetime.timedelta(days=s02b_days)).isoformat()
    plan = {}

    # s02a_jobs 保留：进行中 or requested_at 距今 < s02a_days 天
    rows = c.execute("SELECT id, state, requested_at, finished_at, LENGTH(payload_json) FROM s02a_jobs").fetchall()
    keep_ids, del_ids, del_rows = set(), [], []
    for rid, state, req, fin, ln in rows:
        if fin is None:
            keep_ids.add(rid)
        else:
            try:
                req_ts = datetime.datetime.fromisoformat(req).timestamp()
            except Exception:
                req_ts = 0
            if req_ts >= cut_a:
                keep_ids.add(rid)
            else:
                del_ids.append(rid); del_rows.append((rid, state, req, ln))
    plan['s02a_jobs'] = del_rows

    # s02a_steps / s02a_integrity 按 job_id 删
    for t in ('s02a_steps', 's02a_integrity'):
        if del_ids:
            n = c.execute(f"SELECT COUNT(*) FROM {t} WHERE job_id IN ({','.join('?'*len(del_ids))})", del_ids).fetchone()[0]
            plan[t] = n
        else:
            plan[t] = 0

    # s02a_profiles 按 created_at 距今 < s02a_days 保留
    rows = c.execute("SELECT id, created_at, LENGTH(payload_json) FROM s02a_profiles").fetchall()
    del_profiles, keep_n = [], 0
    for pid, created, ln in rows:
        try:
            ts = datetime.datetime.fromisoformat(created).timestamp()
        except Exception:
            ts = 0
        if ts >= cut_a:
            keep_n += 1
        else:
            del_profiles.append((pid, created, ln))
    plan['s02a_profiles'] = del_profiles

    # s02b_revisions 保留：head 指向 + created_at 距今 < s02b_days 天
    head_ids = {r[0] for r in c.execute("SELECT revision_id FROM s02b_heads")}
    rows = c.execute("SELECT id, base_batch_id, code, trade_date, created_at, LENGTH(payload_json) FROM s02b_revisions").fetchall()
    del_revs, keep_rev = [], 0
    for rid, bb, code, td, created, ln in rows:
        if rid in head_ids or created >= cut_b_iso:
            keep_rev += 1
        else:
            del_revs.append((rid, bb, code, td, created, ln))
    plan['s02b_revisions'] = del_revs

    if del_revs:
        ids = [r[0] for r in del_revs]
        n = c.execute(f"SELECT COUNT(*) FROM s02b_revisions_fact WHERE id IN ({','.join('?'*len(ids))})", ids).fetchone()[0]
        plan['s02b_revisions_fact'] = n
    else:
        plan['s02b_revisions_fact'] = 0
    return plan

def execute_clean(conn, plan):
    c = conn.cursor()
    c.execute('BEGIN IMMEDIATE')
    del_jobs = [r[0] for r in plan['s02a_jobs']]
    if del_jobs:
        ph = ','.join('?'*len(del_jobs))
        for t in ('s02a_steps', 's02a_integrity'):
            c.execute(f"DELETE FROM {t} WHERE job_id IN ({ph})", del_jobs)
        c.execute(f"DELETE FROM s02a_jobs WHERE id IN ({ph})", del_jobs)
    if plan['s02a_profiles']:
        ids = [r[0] for r in plan['s02a_profiles']]
        ph = ','.join('?'*len(ids))
        c.execute(f"DELETE FROM s02a_profiles WHERE id IN ({ph})", ids)
    del_revs = [r[0] for r in plan['s02b_revisions']]
    if del_revs:
        ph = ','.join('?'*len(del_revs))
        c.execute(f"DELETE FROM s02b_revisions_fact WHERE id IN ({ph})", del_revs)
        c.execute(f"DELETE FROM s02b_revisions WHERE id IN ({ph})", del_revs)
    conn.commit()

def clean_orphan_blobs(hot_conn, ev_conn):
    """证据库清理：删掉热库已不引用的 blob（只删 s02b 清理后变孤立的，全表扫描）"""
    c = hot_conn.cursor()
    referenced = set()
    for t, col in [('master_member','blob_id'),('metrics_fact','blob_id'),('quote_fact','blob_id'),
                   ('history_fact','blob_id'),('p50_ref','blob_id'),('batches_fact','input_blob'),
                   ('batches_fact','snapshot_blob'),('batches_fact','manifest_blob'),
                   ('history_assets_fact','source_blob'),('s02b_revisions_fact','blob_id'),
                   ('dashboard_derived_metrics_fact','blob_id'),('research_rows_fact','blob_id'),
                   ('s02lp_inputs_fact','blob_id'),('source_rows_fact','blob_id')]:
        try:
            for (bid,) in c.execute(f"SELECT [{col}] FROM [{t}] WHERE [{col}] IS NOT NULL"):
                referenced.add(int(bid))
        except Exception:
            pass
    e = ev_conn.cursor()
    total = e.execute('SELECT COUNT(*) FROM ev_blob').fetchone()[0]
    orphans = []
    for (bid,) in e.execute('SELECT blob_id FROM ev_blob'):
        if bid not in referenced:
            orphans.append(bid)
    return total, orphans

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=3, help='s02a 保留天数')
    ap.add_argument('--rev-days', type=int, default=7, help='s02b 修订保留天数（head 永远保留）')
    ap.add_argument('--no-vacuum', action='store_true', help='清理后不 VACUUM')
    ap.add_argument('--dry-run', action='store_true', help='只统计不删除')
    args = ap.parse_args()

    print(f'[{now_str()}] 清理计划: s02a 保留 {args.days} 天, s02b 保留 {args.rev_days} 天 (head 永远保留), dry_run={args.dry_run}')

    if not HOT.exists():
        print('错误: 热库不存在', HOT); sys.exit(1)

    # 备份（非 dry-run）
    if not args.dry_run:
        print('备份中...')
        for dst, mb in backup():
            print(f'  已备份: {dst.name} ({mb:.1f} MiB)')

    hot = connect_plain(HOT)
    ev = connect_plain(EVIDENCE)
    try:
        plan = analyze_hot(hot, args.days, args.rev_days)
        print('\n== 待清理统计 ==')
        print(f'  s02a_jobs:      {len(plan["s02a_jobs"])} 条 ({sum(r[3] for r in plan["s02a_jobs"])/1048576:.1f} MiB)')
        print(f'  s02a_steps:     {plan["s02a_steps"]} 条')
        print(f'  s02a_integrity: {plan["s02a_integrity"]} 条')
        print(f'  s02a_profiles:  {len(plan["s02a_profiles"])} 条 ({sum(r[2] for r in plan["s02a_profiles"])/1048576:.1f} MiB)')
        print(f'  s02b_revisions: {len(plan["s02b_revisions"])} 条 ({sum(r[5] for r in plan["s02b_revisions"])/1048576:.1f} MiB)')
        print(f'  s02b_revisions_fact: {plan["s02b_revisions_fact"]} 条')

        if args.dry_run:
            print('\n[dry-run] 未执行删除')
            return

        execute_clean(hot, plan)
        print('\n删除完成')

        # 证据库孤立 blob
        total, orphans = clean_orphan_blobs(hot, ev)
        print(f'\n证据库: 共 {total} blob, 孤立 {len(orphans)} 个')
        if orphans:
            e = ev.cursor()
            e.execute('BEGIN IMMEDIATE')
            for i in range(0, len(orphans), 1000):
                chunk = orphans[i:i+1000]
                ph = ','.join('?'*len(chunk))
                e.execute(f"DELETE FROM ev_blob WHERE blob_id IN ({ph})", chunk)
            ev.commit()
            print(f'  已删除 {len(orphans)} 个孤立 blob')
    finally:
        hot.close(); ev.close()

    if not args.no_vacuum:
        print('\nVACUUM 热库...')
        v = sqlite3.connect(str(HOT), timeout=60)
        try:
            v.execute('VACUUM')
        finally:
            v.close()
        print('VACUUM 证据库...')
        v = sqlite3.connect(str(EVIDENCE), timeout=60)
        try:
            v.execute('VACUUM')
        finally:
            v.close()
        for p, tag in [(HOT, '热库'), (EVIDENCE, '证据库')]:
            print(f'  {tag}: {p.stat().st_size/1048576:.1f} MiB')
    print(f'\n[{now_str()}] 完成')

if __name__ == '__main__':
    main()
