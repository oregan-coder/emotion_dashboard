# -*- coding: utf-8 -*-
"""存量日志压缩：用新的 summarize_steps/sanitized 重写现有 s02a/s02b 日志 payload。
- s02a_jobs: steps -> summarize_steps，其余字段 sanitized(预算截断)
- s02a_steps / s02a_integrity / s02a_profiles / s02a_checkpoints: sanitized 重写
- 只动 s02a* 日志表，不碰任何业务表
- --dry-run 只统计
"""
import sqlite3, pathlib, sys, json, io, datetime

sys.path.insert(0, r'F:\PythonProject\emotion_dashboard\_5535_runtime\5535_UI_PRESERVED_2_1_8b457d4677495bf3')
os_environ_nop = None
from s02_daily.common import sanitized, summarize_steps, decode

HOT = r'F:\PythonProject\emotion_dashboard\data\.migration_shadow\market_store_5535.next.sqlite3'
BACKUP = pathlib.Path(r'F:\PythonProject\emotion_dashboard\.5535_backups')
DRY = '--dry-run' in sys.argv

def backup():
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    BACKUP.mkdir(exist_ok=True)
    dst = BACKUP / f'hot_{stamp}_pre_logcompact.sqlite3'
    s = sqlite3.connect(HOT); d = sqlite3.connect(str(dst))
    with d: s.backup(d)
    d.close(); s.close()
    print(f'备份: {dst.name} ({dst.stat().st_size/1048576:.1f} MiB)')

def compress_job_payload(raw):
    j = decode(raw)
    if not isinstance(j, dict): return raw
    if isinstance(j.get('steps'), list) and j['steps']:
        j['steps'] = summarize_steps(j['steps'])
    # 其余字段也走预算截断（coverage/display 等大字段）
    j = sanitized(j)
    return json.dumps(j, ensure_ascii=False)

def compress_integrity(raw):
    """s02a_integrity: candidates/snapshot_candidates 只留 code 级摘要，
    research_rows 只留行摘要，day_reports 只留 kind/batch_id/payload 前 500 字，
    其余字段 sanitized 预算截断。保留 status/sha 等小标量。"""
    try:
        v = decode(raw)
        if not isinstance(v, dict): return raw
        out = {}
        for k, val in v.items():
            if k in ('research_rows',):
                rows = []
                for r in val if isinstance(val, list) else []:
                    if not isinstance(r, dict): continue
                    rows.append({kk: r.get(kk) for kk in ('code', 'kind', 'row_no') if kk in r})
                out[k] = rows
            elif k in ('candidates', 'snapshot_candidates'):
                rows = []
                for r in val if isinstance(val, list) else []:
                    if isinstance(r, dict) and r.get('code'):
                        rows.append({'code': r.get('code')})
                out[k] = rows
            elif k == 'day_reports':
                rows = []
                for r in val if isinstance(val, list) else []:
                    if not isinstance(r, dict): continue
                    p = r.get('payload')
                    rows.append({'batch_id': r.get('batch_id'), 'kind': r.get('kind'),
                                 'payload_head': str(p)[:500] if p else None})
                out[k] = rows
            else:
                out[k] = val
        return json.dumps(sanitized(out), ensure_ascii=False)
    except Exception:
        return raw


def compress_plain(raw, as_step=False):
    try:
        v = decode(raw)
        if as_step:
            v = summarize_steps(v if isinstance(v, list) else [v])
            return json.dumps(v, ensure_ascii=False)
        return json.dumps(sanitized(v), ensure_ascii=False)
    except Exception:
        return raw

def main():
    con = sqlite3.connect(HOT)
    c = con.cursor()
    plan = []
    # s02a_jobs
    for rid, raw in c.execute('SELECT id, payload_json FROM s02a_jobs').fetchall():
        new = compress_job_payload(raw)
        plan.append(('s02a_jobs', rid, len(raw), len(new), new if not DRY else None))
    # 其余表按行重写
    for table, col in [('s02a_steps','job_id'), ('s02a_integrity','job_id'), ('s02a_profiles','id')]:
        cols = [r[1] for r in c.execute(f'PRAGMA table_info({table})').fetchall()]
        idcol = 'id' if 'id' in cols else 'job_id'
        for pk, raw in c.execute(f'SELECT {idcol}, payload_json FROM {table}').fetchall():
            if table == 's02a_steps':
                new = compress_plain(raw, as_step=True)
            elif table == 's02a_integrity':
                new = compress_integrity(raw)
            else:
                new = compress_plain(raw)
            plan.append((table, pk, len(raw), len(new), new if not DRY else None))
    # checkpoints
    for pk, raw in c.execute('SELECT batch_id, payload_json FROM s02a_checkpoints').fetchall():
        new = compress_job_payload(raw)
        plan.append(('s02a_checkpoints', pk, len(raw), len(new), new if not DRY else None))

    before = sum(p[2] for p in plan)
    after = sum(p[3] for p in plan)
    print(f'{"表":22s} {"条数":>6s} {"压缩前":>10s} {"压缩后":>10s}')
    per = {}
    for t, _, b, a, _ in plan:
        per.setdefault(t, [0,0,0])
        per[t][0]+=1; per[t][1]+=b; per[t][2]+=a
    for t,(n,b,a) in sorted(per.items(), key=lambda x:-x[1][1]):
        print(f'{t:22s} {n:>6,} {b/1048576:>9.2f} MiB {a/1048576:>9.2f} MiB')
    print(f'{"合计":22s} {len(plan):>6,} {before/1048576:>9.2f} MiB {after/1048576:>9.2f} MiB  (节省 {(before-after)/1048576:.1f} MiB)')
    if DRY:
        print('\n[dry-run] 未写入'); con.close(); return
    c.execute('BEGIN IMMEDIATE')
    for t, pk, _, _, new in plan:
        if t == 's02a_jobs': c.execute('UPDATE s02a_jobs SET payload_json=? WHERE id=?', (new, pk))
        elif t == 's02a_steps': c.execute('UPDATE s02a_steps SET payload_json=? WHERE job_id=?', (new, pk))
        elif t == 's02a_integrity': c.execute('UPDATE s02a_integrity SET payload_json=? WHERE job_id=?', (new, pk))
        elif t == 's02a_profiles': c.execute('UPDATE s02a_profiles SET payload_json=? WHERE id=?', (new, pk))
        elif t == 's02a_checkpoints': c.execute('UPDATE s02a_checkpoints SET payload_json=? WHERE batch_id=?', (new, pk))
    con.commit()
    con.close()
    print('\n写入完成')

if __name__ == '__main__':
    if not DRY: backup()
    main()
