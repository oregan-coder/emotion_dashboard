"""883900 tail repair. No network/writes on import or display reads.
Preserves original make_view arithmetic and frozen existing daily heads.
"""
from __future__ import annotations
import copy
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from . import common as C, storage as S

VERSION = 'M8839_TAIL_FRESHNESS_R1'
CALENDAR_KEY = 'tail_calendar_r1'
COOLDOWN_KEY = 'tail_source_cooldown_r1'

class TailError(ValueError):
    pass


def decode(value):
    if isinstance(value, dict):
        return value
    return json.loads(value) if value else {}


def calendar_days(obj):
    """Accept actual producer's `dates`, in addition to legacy schema names."""
    if not isinstance(obj, dict) or not (obj.get('verified') is True or obj.get('status') == 'VALID'):
        return []
    out = set()
    for key in ('days', 'dates', 'trade_dates', 'display_dates'):
        values = obj.get(key)
        if isinstance(values, list):
            out.update(d for x in values if (d := C.day(x)))
    return sorted(out)


def saved_calendar(db):
    with C.connect(db) as con:
        row = con.execute('SELECT value FROM m8839_meta WHERE key=?', (CALENDAR_KEY,)).fetchone()
        return decode(row[0]) if row else {}


def read_calendar_evidence(project, db):
    """Read selected calendar heads and verified producer inputs, tables OR views.
    Do not create a migration shim or infer holidays from missing quote rows.
    """
    found, issues = [], []
    with C.connect(db) as con:
        names = {r[0] for r in con.execute("SELECT name,type FROM sqlite_master WHERE type IN ('table','view')")}
        if {'p50_heads', 'p50_revisions'} <= names:
            try:
                rows = con.execute("SELECT r.id,r.payload_json FROM p50_heads h JOIN p50_revisions r ON r.id=h.revision_id AND r.kind=h.kind AND r.key=h.key WHERE h.kind='calendar' AND h.key='CN_A'")
                for r in rows:
                    found.append(('p50:' + r['id'], decode(r['payload_json'])))
            except Exception as exc:
                issues.append({'source': 'p50_calendar', 'error': str(exc)[:300]})
        if {'published_days', 'batches'} <= names:
            try:
                rows = con.execute('SELECT b.id,b.trade_date,b.input_json,b.snapshot_json FROM published_days p JOIN batches b ON b.id=p.batch_id AND b.trade_date=p.trade_date ORDER BY p.trade_date DESC LIMIT 2')
                for row in rows:
                    for col in ('snapshot_json', 'input_json'):
                        obj = decode(row[col])
                        for key, cal in [('calendar', obj.get('calendar')), ('input_evidence.calendar', (obj.get('input_evidence') or {}).get('calendar')), ('approved_input.calendar', (obj.get('approved_input') or {}).get('calendar')), ('approved_bundle.calendar', (obj.get('approved_bundle') or {}).get('calendar'))]:
                            if isinstance(cal, dict):
                                found.append((row['id'] + ':' + col + ':' + key, cal))
            except Exception as exc:
                issues.append({'source': 'published_input_calendar', 'error': str(exc)[:300]})
        if 'm8839_meta' in names:
            row = con.execute('SELECT value FROM m8839_meta WHERE key=?', (CALENDAR_KEY,)).fetchone()
            if row:
                found.append(('m8839_meta:' + CALENDAR_KEY, decode(row[0])))
    days, origins = set(), []
    for origin, obj in found:
        ds = calendar_days(obj)
        if ds:
            days.update(ds)
            origins.append({'origin': origin, 'first': ds[0], 'last': ds[-1], 'count': len(ds), 'digest': C.digest(ds)})
    return {'status': 'VALID' if days else 'PENDING', 'verified': bool(days), 'days': sorted(days), 'origins': origins, 'issues': issues}


class DatedRows(dict):
    """Extra calendar metadata is an attribute, not a fake date/price dict row."""
    pass


def wrap_make_view(original):
    def make_view(calendar, records, end, start='20260701'):
        cal = set(d for d in calendar if C.day(d) == d)
        cal.update(getattr(records, 'verified_calendar', []))
        # Keep *every* saved 883900 date, not just `end` (21 must survive at 22).
        cal.update(d for d in records if C.day(d) == d)
        if C.day(end) != end:
            raise TailError('INVALID_VIEW_END')
        known_end = end in cal
        # This is a null placeholder, never fabricated market data.
        cal.add(end)
        out = original(sorted(cal), records, end, start)
        current = out.get('current') or {}
        ready = (current.get('date') == end and current.get('status') == 'VALID'
                 and current.get('earning_effect') is not None and current.get('fund_cycle') is not None)
        if not ready:
            out['status'] = 'PARTIAL'
        out['freshness'] = {
            'policy': VERSION, 'requested_end': end, 'target_in_verified_calendar_or_saved_rows': known_end,
            'latest_daily': max((r['date'] for r in out.get('history', []) if r.get('earning_effect') is not None), default=None),
            'target_complete': ready,
            'missing_daily': [r['date'] for r in out.get('history', []) if r.get('earning_effect') is None],
            'notice': None if ready else '目标日或五交易日窗口仍缺原生指数数据；旧日期完整不代表目标日完成。',
        }
        return out
    make_view._m8839_tail_r1 = True
    return make_view


def install_view_wrappers():
    """Pure binding changes; protected files themselves stay byte-for-byte intact."""
    from . import money_view
    if not getattr(S.daily_rows, '_m8839_tail_r1', False):
        original = S.daily_rows
        def rows(db):
            result = DatedRows(original(db))
            result.verified_calendar = calendar_days(saved_calendar(db))
            return result
        rows._m8839_tail_r1 = True
        S.daily_rows = rows
    old_view = money_view.make_view
    if not getattr(old_view, '_m8839_tail_r1', False):
        money_view.make_view = wrap_make_view(old_view)
    # The original package __init__ imports web before this append-only hook.
    # Update that already-imported function alias, not the protected source file.
    web_module = sys.modules.get(__package__ + '.web')
    if web_module is not None and getattr(web_module, 'make_view', None) is old_view:
        web_module.make_view = money_view.make_view


def bounded_worker(config, project, timeout=65):
    env = os.environ.copy()
    # No token/cookie use or environment dump in this repair path.
    for key in ('THS_COOKIE', 'TUSHARE_TOKEN'):
        env.pop(key, None)
    env['PYTHONPATH'] = str(Path(project).resolve()) + os.pathsep + env.get('PYTHONPATH', '')
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    try:
        proc = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-m', 'market_speed_883900.source_tail_r1'], input=C.dumps(config), text=True, encoding='utf-8', errors='replace', capture_output=True, cwd=str(project), env=env, timeout=timeout)
        text = proc.stdout.strip().splitlines()
        if not text:
            return {'ok': False, 'status': 'WORKER_NO_JSON', 'requests': None, 'stderr': proc.stderr[-1200:]}
        result = json.loads(text[-1])
        if not isinstance(result, dict):
            raise ValueError('worker root')
        return result
    except subprocess.TimeoutExpired:
        return {'ok': False, 'status': 'SOURCE_TIMEOUT_NO_FAKE_VALUES', 'worker_reaped': True, 'requests': None}
    except Exception as exc:
        return {'ok': False, 'status': 'WORKER_FAILED', 'requests': None, 'error_type': type(exc).__name__, 'error': str(exc)[:400]}


def equal_quote(existing, row):
    for a, b, tol in [('pct', 'pct', .03), ('close_value', 'close', .011), ('preclose_value', 'preclose', .011)]:
        x, y = C.number(existing.get(a)), C.number(row.get(b))
        if x is None or y is None or abs(x-y) > tol:
            return False
    return True


def validate_bundle(bundle, calendar, expected, existing):
    if not calendar_days(calendar):
        raise TailError('NO_VERIFIED_CALENDAR')
    known = set(calendar_days(calendar))
    by_date = {}
    for row in bundle.get('daily', []):
        d = row.get('date')
        if C.day(d) != d or d not in known or row.get('source_date') != d or row.get('source') != C.SERIES:
            raise TailError('UNVERIFIED_SOURCE_DATE_OR_SERIES')
        if d in by_date and by_date[d] != row:
            raise TailError('DUPLICATE_DAY_CONFLICT')
        close, pre, pct = (C.number(row.get(k)) for k in ('close', 'preclose', 'pct'))
        if close is None or pre is None or pct is None or close <= 0 or pre <= 0 or not -100 < pct < 100:
            raise TailError('INVALID_DAILY_VALUES')
        if abs((close/pre-1)*100-pct) > .03:
            raise TailError('DAILY_PCT_CLOSE_CONFLICT')
        by_date[d] = row
    missing = [d for d in expected if d not in by_date and d not in existing]
    if missing:
        raise TailError('TARGET_DATES_MISSING:' + ','.join(missing))
    # Do not let a refreshed raw response overwrite or silently disagree with an
    # already frozen dependency. Existing old heads are never changed.
    conflicts = [d for d, row in by_date.items() if d in existing and not equal_quote(existing[d], row)]
    if conflicts:
        raise TailError('EXISTING_FROZEN_DEPENDENCY_CONFLICT:' + ','.join(conflicts))
    cal = sorted(known)
    for d, row in by_date.items():
        i = cal.index(d)
        prev = cal[i-1] if i else None
        older = by_date.get(prev)
        pc = C.number(older.get('close')) if older else C.number((existing.get(prev) or {}).get('close_value'))
        if pc is not None and abs(pc-row['preclose']) > .011:
            raise TailError('ADJACENT_CLOSE_CHAIN_CONFLICT:' + d)
    resp = bundle.get('response') or {}
    if not resp.get('id') or not isinstance(resp.get('raw_text'), str) or not resp['raw_text']:
        raise TailError('RAW_EVIDENCE_REQUIRED')
    return by_date


def save_missing_atomic(db, bundle, calendar, allowed, baseline):
    """One transaction, only insert missing days, no UPDATE of an existing head."""
    inserted = []
    response = bundle['response']
    with C.connect(db, True, timeout=5) as con:
        con.execute('BEGIN IMMEDIATE')
        try:
            for d in allowed:
                old = con.execute('SELECT revision_id FROM m8839_heads WHERE trade_date=?', (d,)).fetchone()
                prev = baseline.get(d)
                if (old[0] if old else None) != (prev.get('id') if prev else None):
                    raise TailError('CONCURRENT_HEAD_CHANGE:' + d)
            con.execute('INSERT OR IGNORE INTO m8839_response VALUES(?,?,?,?,?,?,?)',
                (response['id'], response['provider'], C.CODE, response['received_at'], response.get('url'), response['raw_text'], C.dumps(response.get('metadata', {}))))
            for row in bundle['daily']:
                d = row['date']
                if d not in allowed or d in baseline:
                    continue
                data = dict(row, code=C.CODE, response_id=response['id'])
                ident = C.digest(data)
                con.execute('INSERT OR IGNORE INTO m8839_daily VALUES(?,?,?,?,?,?,?,?,?,?)', (ident, d, C.CODE, row['pct'], row['close'], row['preclose'], row['method'], response['id'], C.dumps(data), C.now_iso()))
                con.execute('INSERT INTO m8839_heads VALUES(?,?)', (d, ident))
                inserted.append(d)
            # `calendar` retains native raw response, or exact selected DB origins.
            con.execute('INSERT INTO m8839_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (CALENDAR_KEY, C.dumps(calendar)))
            # Some split-DB migrations omit legacy head triggers. Invalidate
            # explicitly in the SAME transaction, never rely only on a trigger.
            cur = con.execute("UPDATE m8839_meta SET value=CAST(value AS INTEGER)+1 WHERE key='display_epoch'")
            if cur.rowcount != 1:
                raise TailError('DISPLAY_EPOCH_MISSING')
            con.commit()
        except BaseException:
            con.rollback()
            raise
    return inserted


def cooldown(db, now):
    with C.connect(db) as con:
        row = con.execute('SELECT value FROM m8839_meta WHERE key=?', (COOLDOWN_KEY,)).fetchone()
        obj = decode(row[0]) if row else {}
        return obj if C.number(obj.get('until_epoch')) and obj['until_epoch'] > now else None


def set_cooldown(db, seconds, reason):
    with C.connect(db, True) as con:
        con.execute('INSERT INTO m8839_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (COOLDOWN_KEY, C.dumps({'until_epoch': time.time()+seconds, 'reason': reason})))
        con.commit()


def sync_index(project, start='20260701', end=None, mode='history', allow_during_update=False, adapter=None, fetcher=None):
    """Compatibility entry for the EXISTING daily-update hook. No full-market run.
    Default latest covers at most the latest 8 verified sessions; historical
    omissions before that remain reported, not silently backfilled.
    """
    project = Path(project).resolve()
    db = C.database(project)
    ident, begun = uuid.uuid4().hex, time.time()
    report = {'policy': VERSION, 'run_id': ident, 'status': 'PENDING', 'writes_daily': False, 'requests': 0, 'source': C.SERIES,
              'original_history_heads_rewritten': 0, 'scope': 'RECENT_TAIL_AND_REQUIRED_WARMUP_ONLY'}
    leased = False
    try:
        if adapter:
            raise TailError('THIS_REPAIR_NO_TOKEN_COOKIE_OR_CUSTOM_ADAPTER')
        if C.update_running(db) and not allow_during_update:
            report['status'] = 'YIELD_TO_DAILY_UPDATE'
            return report
        if not S.active(db):
            raise TailError('EXPECTED_EXISTING_883900_ACTIVE_NO_IMPLICIT_SOURCE_SWITCH')
        now = C.china_now()
        today = now.strftime('%Y%m%d')
        ceiling = today if (now.hour, now.minute) >= (15, 30) else (now-dt.timedelta(days=1)).strftime('%Y%m%d')
        requested = C.day(end) if end is not None else ceiling
        if not requested:
            raise TailError('INVALID_END_DATE')
        report.update(requested_end=requested, local_time=now.isoformat(), finalization_cutoff='15:30 Asia/Shanghai')
        if requested > ceiling:
            report['status'] = 'REQUEST_NOT_FINALIZED'
            return report
        existing = S.daily_rows(db)
        cal = read_calendar_evidence(project, db)
        # Crucially do NOT clamp requested to latest_finished(old_calendar).
        report['calendar_before'] = {k:v for k,v in cal.items() if k != 'days'}
        report['calendar_before']['last'] = max(cal['days'], default=None)
        known = calendar_days(cal)
        new_cal_needed = not known or max(known) < requested
        if not new_cal_needed:
            finished = max((d for d in known if d <= requested), default=None)
            if not finished:
                raise TailError('CALENDAR_HAS_NO_COMPLETED_SESSION')
            if end is not None and requested not in known:
                report['status'] = 'REQUEST_IS_NOT_TRADING_DAY'
                return report
            wanted_end = finished
            tail = [d for d in known if d <= finished][-8:]
            want_start = C.day(start)
            targets = [d for d in tail if not want_start or d >= want_start]
            if not targets:
                raise TailError('NO_RECENT_TARGET_DAYS')
            needed = [d for d in known if d <= finished][-12:]
            # All valid and including end? No outbound traffic or daily writes.
            from .money_view import make_view
            view = make_view(known, existing, finished, targets[0])
            if all(d in existing for d in targets) and view['status'] == 'READY':
                # Still persist a newer verified calendar so every display path
                # uses it. This is metadata only, no fake index values.
                old_cal = calendar_days(saved_calendar(db))
                if set(known) - set(old_cal):
                    with C.connect(db, True) as con:
                        con.execute('INSERT INTO m8839_meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (CALENDAR_KEY, C.dumps(cal)))
                        con.execute("UPDATE m8839_meta SET value=CAST(value AS INTEGER)+1 WHERE key='display_epoch'")
                        con.commit()
                report.update(status='ALREADY_COMPLETE', range=[targets[0], finished], target_dates=targets, activated=True)
                return report
        else:
            wanted_end, targets, needed = requested, [], []
        block = cooldown(db, time.time())
        if block:
            report.update(status='SOURCE_COOLDOWN', cooldown=block)
            return report
        # Also exclude another standalone repair, not just the original pipeline.
        if not S.lease(db, '883900_fetch', ident, seconds=110):
            report['status'] = 'ALREADY_RUNNING'
            return report
        leased = True
        config = {'requested_end': requested, 'explicit_end': end is not None, 'start': start,
                  'calendar': cal, 'fetch_calendar': new_cal_needed,
                  'observed_now': now.isoformat(), 'wall_budget_seconds': 55}
        result = (fetcher or bounded_worker)(config, project, 65)
        report['requests'] = result.get('requests')
        report['request_count_known'] = isinstance(report['requests'], int)
        # Includes ALL HTTP raw evidence, including realhead and failures.
        report['source_result'] = result
        if not result.get('ok'):
            report['status'] = result.get('status', 'SOURCE_UNAVAILABLE')
            if result.get('restricted'):
                set_cooldown(db, 900, report['status'])
            return report
        cal = result['calendar']
        known = calendar_days(cal)
        finished = result['end']
        if finished > requested or (end is not None and finished != requested):
            raise TailError('SOURCE_TARGET_DATE_MISMATCH')
        tail = [d for d in known if d <= finished][-8:]
        targets = [d for d in tail if d >= (C.day(start) or tail[0])]
        if not targets or finished not in targets:
            raise TailError('EMPTY_TARGET_WINDOW')
        first = known.index(targets[0])
        allowed = known[max(0, first-4):known.index(finished)+1]
        bundle = copy.deepcopy(result['bundle'])
        bundle['daily'] = [r for r in bundle['daily'] if r['date'] in allowed]
        validate_bundle(bundle, cal, targets, existing)
        # Refuse to save a misleading partial window. Real missing data remains
        # pending with raw evidence; never supplement missing prices with 0.
        staged = dict(existing)
        for r in bundle['daily']:
            if r['date'] not in staged:
                staged[r['date']] = dict(pct=r['pct'], close_value=r['close'], preclose_value=r['preclose'], id='STAGED')
        from .money_view import make_view
        preview = make_view(known, staged, finished, targets[0])
        if preview['status'] != 'READY':
            raise TailError('FIVE_SESSION_DEPENDENCY_MISSING')
        if C.update_running(db) and not allow_during_update:
            report['status'] = 'YIELD_BEFORE_COMMIT'
            return report
        inserted = save_missing_atomic(db, bundle, cal, allowed, existing)
        report.update(database_commit_completed=True, writes_daily=bool(inserted), new_dates=inserted, new_days=len(inserted))
        after = S.daily_rows(db)
        frozen_ok = all(after.get(d) == row for d, row in existing.items())
        check = make_view(known, after, finished, targets[0])
        if not frozen_ok or check['status'] != 'READY':
            raise TailError('POST_COMMIT_INDEPENDENT_READBACK_FAILED')
        report.update(status='COMPLETE', range=[targets[0], finished], target_dates=targets,
                      writes_daily=bool(inserted), new_dates=inserted, new_days=len(inserted), activated=True,
                      db_readback_verified=True, old_heads_and_values_unchanged=frozen_ok,
                      coverage=check['history_coverage'], current=check['current'])
        return report
    except Exception as exc:
        report.update(status='PENDING_INPUT_OR_ERROR', error_type=type(exc).__name__, error=str(exc)[:1000])
        return report
    finally:
        report['elapsed_seconds'] = round(time.time()-begun, 3)
        try:
            S.save_run(db, ident, '883900_tail_r1', begun, report['status'], report)
        except Exception as exc:
            report['run_evidence_error'] = str(exc)[:300]
        if leased:
            try:
                S.release(db, '883900_fetch', ident)
            except Exception as exc:
                report['lease_release_error'] = str(exc)[:300]
