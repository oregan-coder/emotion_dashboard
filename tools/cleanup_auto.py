# -*- coding: utf-8 -*-
"""
5535 热库日志后台自动清理（由采集触发，独立进程运行，不影响采集流程）

策略（与用户确认）：
- s02a 系列（jobs/steps/integrity/profiles/checkpoints）：保留最近 3 天 + 进行中作业
- s02b_revisions：保留 head 指向的 + 最近 7 天；其余删除（s02b_revisions_fact 同步）
- 不备份（自动清理场景；手动清理走 cleanup_logs.py 带备份）
- 尝试 VACUUM；若采集正在写库导致锁冲突则跳过，下次再 VACUUM
- 全程日志写 F 盘 tools/cleanup_log.txt，不向终端抛错

用法（由 web_app 以 subprocess 异步启动）：
  F:\\Python3.13\\python.exe -S tools\\cleanup_auto.py
"""
import sqlite3, pathlib, time, datetime, traceback, sys

HOT = pathlib.Path(r'F:\PythonProject\emotion_dashboard\data\.migration_shadow\market_store_5535.next.sqlite3')
EV = pathlib.Path(r'F:\PythonProject\emotion_dashboard\data\.migration_shadow\evidence_5535.next.sqlite3')
LOG = pathlib.Path(r'F:\PythonProject\emotion_dashboard\tools\cleanup_log.txt')
S02A_DAYS = 3      # s02a 保留天数
S02B_DAYS = 7      # s02b 保留天数（head 永远保留）
VACUUM_TIMEOUT_S = 30  # VACUUM 锁等待上限，超过跳过
UI_JOB_STALE_S = 15 * 60
UI_JOB_KEEP_DAYS = 7

def log(msg):
    line = f'[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}'
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass

def main():
    log('=== 自动清理开始 ===')
    if not HOT.exists():
        log('热库不存在，跳过'); return

    hot = sqlite3.connect(str(HOT), timeout=VACUUM_TIMEOUT_S)
    try:
        c = hot.cursor()
        cut_a = (time.time() - S02A_DAYS * 86400)
        cut_b = (datetime.datetime.now() - datetime.timedelta(days=S02B_DAYS)).isoformat()

        # ---- UI 更新/补录任务：先封闭长时间无心跳与不完整终态，再按保留期清理 ----
        c.execute('''CREATE TABLE IF NOT EXISTS ui_update_jobs (
            id TEXT PRIMARY KEY, target_key TEXT NOT NULL, target_date TEXT,
            mode TEXT NOT NULL, state TEXT NOT NULL, requested_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, finished_at TEXT, progress_json TEXT NOT NULL,
            result_json TEXT, error TEXT, error_type TEXT)''')
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        ui_rows = c.execute('SELECT id,state,updated_at,finished_at,result_json FROM ui_update_jobs').fetchall()
        stale_ui = 0
        for jid, state, updated, finished, result_json in ui_rows:
            if state == 'RUNNING':
                try:
                    age = time.time() - datetime.datetime.fromisoformat(updated).timestamp()
                except Exception:
                    age = UI_JOB_STALE_S + 1
                if age > UI_JOB_STALE_S:
                    c.execute("UPDATE ui_update_jobs SET state='STALE', updated_at=?, finished_at=?, error=?, error_type=? WHERE id=?",
                              (now_iso, now_iso, '超过15分钟无进度心跳', 'STALE_TIMEOUT', jid))
                    stale_ui += 1
            elif state == 'DONE' and (result_json is None or result_json in ('', 'null')):
                c.execute("UPDATE ui_update_jobs SET state='INCOMPLETE', updated_at=?, error=?, error_type=? WHERE id=?",
                          (now_iso, '任务已结束但没有结果摘要', 'RESULT_MISSING', jid))
        if stale_ui:
            log(f'ui_update_jobs: 标记无心跳任务 {stale_ui} 条为 STALE')
        ui_cut = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=UI_JOB_KEEP_DAYS)
        old_ui = []
        for jid, state, updated, finished, result_json in ui_rows:
            try:
                ts = datetime.datetime.fromisoformat(updated).astimezone(datetime.timezone.utc)
            except Exception:
                ts = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
            if state != 'RUNNING' and ts < ui_cut:
                old_ui.append(jid)
        if old_ui:
            ph = ','.join('?' * len(old_ui))
            c.execute(f'DELETE FROM ui_update_jobs WHERE id IN ({ph})', old_ui)
            log(f'ui_update_jobs: 清理超过{UI_JOB_KEEP_DAYS}天终态 {len(old_ui)} 条')

        # ---- 旧 S02A 作业：finished_at 为空不再永久保留 ----
        stale_s02a = 0
        for jid, state, updated in c.execute("SELECT id,state,updated_at FROM s02a_jobs WHERE finished_at IS NULL").fetchall():
            try:
                age = time.time() - datetime.datetime.fromisoformat(updated).timestamp()
            except Exception:
                age = UI_JOB_STALE_S + 1
            if age > UI_JOB_STALE_S:
                c.execute("UPDATE s02a_jobs SET state='STALE_TIMEOUT', updated_at=?, finished_at=? WHERE id=?",
                          (now_iso, now_iso, jid))
                stale_s02a += 1
        if stale_s02a:
            log(f's02a_jobs: 标记无心跳作业 {stale_s02a} 条为 STALE_TIMEOUT')

        # ---- s02a_jobs：进行中(finished_at IS NULL) 或 requested_at 距今 < S02A_DAYS 保留 ----
        rows = c.execute('SELECT id, requested_at, finished_at FROM s02a_jobs').fetchall()
        del_ids, keep_n = [], 0
        for rid, req, fin in rows:
            if fin is None:
                keep_n += 1; continue
            try:
                req_ts = datetime.datetime.fromisoformat(req).timestamp()
            except Exception:
                req_ts = 0
            if req_ts >= cut_a: keep_n += 1
            else: del_ids.append(rid)
        log(f's02a_jobs: 总{len(rows)} 保留{keep_n} 删除{len(del_ids)}')
        if del_ids:
            ph = ','.join('?' * len(del_ids))
            for t in ('s02a_steps', 's02a_integrity'):
                n = c.execute(f'DELETE FROM {t} WHERE job_id IN ({ph})', del_ids).rowcount
                log(f'  {t}: 删 {n}')
            n = c.execute(f'DELETE FROM s02a_jobs WHERE id IN ({ph})', del_ids).rowcount
            log(f'  s02a_jobs: 删 {n}')

        # ---- s02a_profiles：created_at 距今 < S02A_DAYS 保留 ----
        rows = c.execute('SELECT id, created_at FROM s02a_profiles').fetchall()
        del_ids = []
        for pid, created in rows:
            try: ts = datetime.datetime.fromisoformat(created).timestamp()
            except Exception: ts = 0
            if ts < cut_a: del_ids.append(pid)
        if del_ids:
            ph = ','.join('?' * len(del_ids))
            n = c.execute(f'DELETE FROM s02a_profiles WHERE id IN ({ph})', del_ids).rowcount
            log(f's02a_profiles: 删 {n}')

        # ---- s02a_checkpoints：batch 对应日期（由 payload 判断）不在此清，保留最近 N 天批次 ----
        # 简单起见按 payload 里 target_date 保留（若无法解析则保留）
        rows = c.execute('SELECT batch_id, payload_json FROM s02a_checkpoints').fetchall()
        del_batches = []
        for bid, payload in rows:
            try:
                import json as _json
                j = _json.loads(payload)
                td = j.get('target_date')
                if td:
                    ts = datetime.datetime.strptime(str(td), '%Y%m%d').timestamp()
                    if ts < cut_a: del_batches.append(bid)
            except Exception:
                pass
        if del_batches:
            ph = ','.join('?' * len(del_batches))
            n = c.execute(f'DELETE FROM s02a_checkpoints WHERE batch_id IN ({ph})', del_batches).rowcount
            log(f's02a_checkpoints: 删 {n}')

        # ---- s02b_revisions：head 指向 + created_at 距今 < S02B_DAYS 保留 ----
        head_ids = {r[0] for r in c.execute('SELECT revision_id FROM s02b_heads')}
        rows = c.execute('SELECT id FROM s02b_revisions').fetchall()
        del_revs = []
        for (rid,) in rows:
            if rid in head_ids: continue
            created = c.execute('SELECT created_at FROM s02b_revisions WHERE id=?', (rid,)).fetchone()[0]
            if created < cut_b: del_revs.append(rid)
        log(f's02b_revisions: 总{len(rows)} head保留{len(head_ids)} 删除{len(del_revs)}')
        if del_revs:
            ph = ','.join('?' * len(del_revs))
            n = c.execute(f'DELETE FROM s02b_revisions_fact WHERE id IN ({ph})', del_revs).rowcount
            log(f'  s02b_revisions_fact: 删 {n}')
            n = c.execute(f'DELETE FROM s02b_revisions WHERE id IN ({ph})', del_revs).rowcount
            log(f'  s02b_revisions: 删 {n}')

        hot.commit()
        size_before = HOT.stat().st_size / 1048576
        log(f'提交完成，热库 {size_before:.1f} MiB')
    except Exception as e:
        log(f'清理异常（不影响采集）: {e}')
        log(traceback.format_exc())
        hot.rollback()
        return
    finally:
        hot.close()

    # ---- VACUUM：锁冲突则跳过 ----
    try:
        log('尝试 VACUUM...')
        v = sqlite3.connect(str(HOT), timeout=VACUUM_TIMEOUT_S)
        try:
            v.execute('VACUUM')
        finally:
            v.close()
        log(f'VACUUM 完成，热库 {HOT.stat().st_size/1048576:.1f} MiB')
    except Exception as e:
        log(f'VACUUM 跳过（采集写库锁冲突或异常）: {e}')
    log('=== 自动清理结束 ===')

if __name__ == '__main__':
    try:
        main()
    except Exception:
        try:
            log('顶层异常: ' + traceback.format_exc())
        except Exception:
            pass
