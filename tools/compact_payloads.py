# -*- coding: utf-8 -*-
"""
5535 payload 压缩工具（幂等，可重复运行）— 第二轮 R2：
1. 链截断: 同(batch,code) 只保留 head + head.parent，删更早修订及孤儿 fact
2. s02b_revisions 全表兜底压缩: 任何明文 payload 改 zpack(z1: 前缀)，含 head（写入点已走 zpack，这里兜底）
3. runs / steps / inputs / decisions / evidence / checkpoints 等表兜底压缩
4. ev_blob 孤儿清理: 扫描热库所有 *_blob 列引用，删证据库未被引用的 blob
用法: python tools/compact_payloads.py [--dry-run]
注意: 不自动 VACUUM（避免锁 Web）；如需回收磁盘空间，停 Web 后手动 VACUUM。
"""
import sqlite3, json, sys, time, pathlib, os
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / '_5535_runtime' / '5535_UI_PRESERVED_2_1_8b457d4677495bf3'))
from s02_daily.common import zpack, zopen

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOT = str(ROOT / 'data' / '.migration_shadow' / 'market_store_5535.next.sqlite3')
# 证据库路径：优先读 .evidence_path，否则同目录 evidence_5535.next.sqlite3
ev_marker = HOT + '.evidence_path'
if os.path.exists(ev_marker):
    EV = open(ev_marker, encoding='utf-8').read().strip()
else:
    EV = str(ROOT / 'data' / '.migration_shadow' / 'evidence_5535.next.sqlite3')

dry = '--dry-run' in sys.argv
RUN_TABLES = ['s02bs_runs','s02cs_runs','s02d_runs','s02lp_runs','s02p_runs','s02q_runs','s02t_runs','s02u_runs','s02f_runs']
# 第二轮需要兜底压缩的其他表（payload_json 列）
OTHER_PAYLOAD_TABLES = [
    's02a_steps','s02q_evidence','s02b_source_objects','s02p_decisions','s02t_decisions',
    's02a_checkpoints','s02t_sources','s02t_inputs','s02bs_inputs','s02cs_inputs',
    's02lp_inputs','s02_scope_freeze_reports','s02a_integrity',
]

con = sqlite3.connect(HOT, timeout=300)
c = con.cursor()
print('模式:', 'DRY-RUN' if dry else 'EXECUTE')
print('热库:', HOT)
print('证据库:', EV)

# ---- 1) 链截断 ----
heads = {}
for b, code, rid in c.execute('SELECT base_batch_id, code, revision_id FROM s02b_heads').fetchall():
    heads[(b, code)] = rid
revs = {}
for rid, p in c.execute('SELECT id, payload_json FROM s02b_revisions').fetchall():
    try:
        j = json.loads(p) if isinstance(p, str) and not p.startswith('z1:') else zopen(p)
        parent = j.get('parent_revision_id')
    except Exception:
        parent = None
    revs[rid] = parent

keep = set()
for (b, code), rid in heads.items():
    keep.add(rid)
    par = revs.get(rid)
    if par: keep.add(par)
all_ids = set(revs.keys())
to_del = all_ids - keep
print(f'[1] 链截断: 总{len(all_ids)} head{len(heads)} 保留{len(keep)} 待删{len(to_del)}')
if to_del and not dry:
    con.execute('BEGIN IMMEDIATE')
    n = c.execute(f'DELETE FROM s02b_revisions WHERE id IN ({",".join("?"*len(to_del))})', sorted(to_del)).rowcount
    print(f'    删修订: {n}')
    nf = c.execute('DELETE FROM s02b_revisions_fact WHERE NOT EXISTS (SELECT 1 FROM s02b_revisions x WHERE x.id=s02b_revisions_fact.id)').rowcount
    print(f'    删孤儿fact: {nf}')
    con.commit()

# ---- 2) s02b_revisions 全表兜底压缩（含 head）----
to_zip = []
for rid in keep:
    row = c.execute('SELECT payload_json FROM s02b_revisions WHERE id=?', (rid,)).fetchone()
    if row and isinstance(row[0], str) and not row[0].startswith('z1:'):
        to_zip.append(rid)
print(f'[2] s02b_revisions 待压缩(明文): {len(to_zip)}')
if to_zip and not dry:
    con.execute('BEGIN IMMEDIATE')
    saved = 0
    for rid in to_zip:
        row = c.execute('SELECT payload_json FROM s02b_revisions WHERE id=?', (rid,)).fetchone()
        if row and isinstance(row[0], str) and not row[0].startswith('z1:'):
            c.execute('UPDATE s02b_revisions SET payload_json=? WHERE id=?', (zpack(json.loads(row[0])), rid))
            saved += 1
    con.commit()
    print(f'    已压缩: {saved}')

# ---- 3) runs 表压缩 ----
print('[3] runs 表压缩:')
existing = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
for t in RUN_TABLES:
    if t not in existing: continue
    rows = c.execute(f'SELECT rowid, payload_json FROM {t}').fetchall()
    todo = [r for r in rows if r[1] and isinstance(r[1], str) and not r[1].startswith('z1:')]
    if dry:
        raw = sum(len(r[1]) for r in todo)
        print(f'    {t}: 总{len(rows)} 待压{len(todo)} 可省{raw/1048576:.1f}MiB')
        continue
    if todo:
        con.execute('BEGIN IMMEDIATE')
        for rowid, payload in todo:
            c.execute(f'UPDATE {t} SET payload_json=? WHERE rowid=?', (zpack(json.loads(payload)), rowid))
        con.commit()
    print(f'    {t}: 压缩 {len(todo)} 条')

# ---- 3b) 其他 payload 表兜底压缩 ----
print('[3b] 其他 payload 表兜底压缩:')
for t in OTHER_PAYLOAD_TABLES:
    if t not in existing: continue
    cols = [r[1] for r in c.execute(f'PRAGMA table_info({t})')]
    if 'payload_json' not in cols:
        continue
    rows = c.execute(f'SELECT rowid, payload_json FROM {t}').fetchall()
    todo = [r for r in rows if r[1] and isinstance(r[1], str) and not r[1].startswith('z1:')]
    if dry:
        raw = sum(len(r[1]) for r in todo)
        print(f'    {t}: 总{len(rows)} 待压{len(todo)} 可省{raw/1048576:.1f}MiB')
        continue
    if todo:
        con.execute('BEGIN IMMEDIATE')
        for rowid, payload in todo:
            c.execute(f'UPDATE {t} SET payload_json=? WHERE rowid=?', (zpack(json.loads(payload)), rowid))
        con.commit()
    if todo:
        print(f'    {t}: 压缩 {len(todo)} 条')

# ---- 4) ev_blob 孤儿清理 ----
# 扫描热库所有表的所有列名含 "blob" 的列，收集被引用 blob_id
print('[4] ev_blob 孤儿清理:')
used = set()
for t in existing:
    cols = [r[1] for r in c.execute(f'PRAGMA table_info({t})')]
    for col in cols:
        if 'blob' not in col.lower(): continue
        try:
            for (bid,) in c.execute(f'SELECT "{col}" FROM "{t}" WHERE "{col}" IS NOT NULL'):
                try: used.add(int(bid))
                except (TypeError, ValueError): pass
        except sqlite3.OperationalError:
            pass
print(f'    热库引用 blob_id: {len(used)}')

ec = sqlite3.connect(EV, timeout=300)
all_bids = {r[0] for r in ec.execute('SELECT blob_id FROM ev_blob')}
orphans = sorted(all_bids - used)
print(f'    ev_blob 总: {len(all_bids)}, 孤儿: {len(orphans)}')
if orphans:
    q = ','.join('?'*len(orphans))
    row = ec.execute(f'SELECT SUM(zlib_len),SUM(orig_len) FROM ev_blob WHERE blob_id IN ({q})', orphans).fetchone()
    print(f'    孤儿 zlib: {(row[0] or 0)/1048576:.1f} MiB, orig: {(row[1] or 0)/1048576:.1f} MiB')
    if not dry:
        ec.execute('BEGIN IMMEDIATE')
        n = ec.execute(f'DELETE FROM ev_blob WHERE blob_id IN ({q})', orphans).rowcount
        ec.commit()
        print(f'    已删: {n}')
ec.close()
con.close()
print('完成（未 VACUUM；如需回收磁盘空间，停 Web 后对两库分别 VACUUM）')
