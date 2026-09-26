# -*- coding: utf-8 -*-
"""
P50 host bindings for project 5535 (emotion_dashboard).

Corrected host-binding candidate based on the supplied P50 return.
Security master and empty-type guards are repaired. The real host engine and
remaining route-builder migration STILL require implementation and host tests.
The archival fallback is explicitly NOT a recomputation. No manual PASS flag.

Rule version is fixed to the user-approved
`5535_approved_input_rules_20260909_v2` from approved_policy.py.
"""
from __future__ import annotations
import copy, json, sqlite3, sys
from pathlib import Path

from p50fix.common import code, day, number, finite, digest, RepairError

RULE_VERSION = '5535_approved_input_rules_20260909_v2'


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _project_root(store):
    """The canonical DB lives at <project>/data/market_store_5535.sqlite3."""
    return Path(store.path).resolve().parents[1]


def _load_cfg(store):
    root = _project_root(store)
    cfg = json.loads((root / 'p50_config.json').read_text(encoding='utf-8-sig'))
    return root, cfg


def _calendar(store, config=None):
    cal = store.get('calendar', 'CN_A')
    if not cal:
        return None
    data = cal['data']
    from core.approved_policy import TradeCalendar
    return TradeCalendar(data.get('days', []), verified=True, source='P50_CALENDAR')


def _master(store, config):
    """Security metadata is NOT query_all_stock's dated trading-status universe.

    The native IPO/outDate/type fields are cached with provenance. Current
    names/status are not proof of historical ST status or membership.
    """
    def usable(obj):
        return (obj.get('schema') == 'P50_NATIVE_SECURITY_MASTER_V2'
                and bool(obj.get('evidence_id'))
                and isinstance(obj.get('members'), dict)
                and bool(obj['members'])
                and all(str(r.get('type', '')) in {'1','2','3'}
                        for r in obj['members'].values()))
    cached = store.get('security_master', 'CN_A')
    if cached and usable(cached['data']):
        return cached['data']
    from p50fix.providers import Client
    from p50fix.pipeline import closed_end
    cal = store.get('calendar', 'CN_A')
    end = cal['data']['days'][-1] if cal and cal['data'].get('days') else closed_end()
    env = Client(store, config.get('timeout_seconds',75),
                 config.get('retries',1), config.get('min_interval',.4)).fetch(
                     'baostock', 'security_master', {'date':end})
    by = {}
    for raw in env['rows']:
        rawcode = str(raw.get('code',''))
        if not rawcode.startswith(('sh.','sz.')):
            continue
        c = code(rawcode)
        typ = str(raw.get('type','')).strip()
        # Missing a type is a data error, NOT evidence of a non-stock entity.
        if typ not in {'1','2','3'}:
            raise RepairError('SECURITY_MASTER_NATIVE_TYPE_MISSING:'+c)
        ipo = str(raw.get('ipoDate','') or '').strip()
        if typ == '1' and not ipo:
            raise RepairError('SECURITY_MASTER_NATIVE_IPO_DATE_MISSING:'+c)
        ent = {'type':typ, 'ipo_date':day(ipo) if ipo else None,
               'out_date':str(raw.get('outDate','') or '').strip() or None,
               'name':str(raw.get('code_name','') or ''),
               'raw_row':raw}
        if c in by and by[c] != ent:
            raise RepairError('SECURITY_MASTER_DUPLICATE_CONFLICT:'+c)
        by[c] = ent
    obj={'schema':'P50_NATIVE_SECURITY_MASTER_V2','members':by,
         'evidence_id':env['evidence_id'],'provider':'baostock',
         'retrieved_at':env.get('retrieved_at'),'rule_version':RULE_VERSION,
         'historical_membership_proof':False}
    if not usable(obj):raise RepairError('SECURITY_MASTER_EMPTY_OR_INCOMPLETE')
    store.put('security_master','CN_A',obj)
    return obj


def _original_db_path(store, config):
    root = _project_root(store)
    if config.get('database'):
        return Path(config['database']).resolve()
    return root / 'data' / 'market_store_5535.sqlite3'


# --------------------------------------------------------------------------
# 1. existing_scope_policy
# --------------------------------------------------------------------------
def existing_scope_policy(store, date, members, envelope, config):
    """Apply the ORIGINAL approved v2 scope decisions to a dated limit-pool.

    `members` are dated pool rows (with raw_row provenance). The pool date is
    the observation date; source_date is set to the pool date because the
    response-date proof (pool_date_proof / tushare trade_date) already bound
    the rows to that session. Listing date and entity type come from the
    dated security master. Unknowns stay UNKNOWN (evidence pending).
    """
    d = day(date)
    from core.approved_policy import scope_decision, exchange_board
    calendar = _calendar(store, config)
    master = _master(store, config)
    if calendar is None:
        raise RepairError('VERIFIED_CALENDAR_REQUIRED_BEFORE_SCOPE')
    decisions = []
    for m in members:
        c = code(m['code'])
        ent = master['members'].get(c, {})
        record = {
            'code': c,
            'name': m.get('name'),
            'source_date': d,
            'market_board': exchange_board(c),
            'is_st': None,
            'listing_date': ent.get('ipo_date'),
        }
        dec = scope_decision(record, d, calendar)
        dec['evidence_id'] = digest({
            'rule': RULE_VERSION, 'code': c, 'date': d,
            'status': dec['status'], 'reasons': dec['reasons'],
            'master_present': bool(ent), 'entity_type': ent.get('type'),
        })
        decisions.append(dec)
    return {
        'rule_version': RULE_VERSION,
        'decisions': decisions,
        'evidence_base': master['evidence_id'],
        'scope_source': 'ORIGINAL_APPROVED_POLICY_v2',
    }


# --------------------------------------------------------------------------
# 2. classify_dated_eod_with_original_rules
# --------------------------------------------------------------------------
def classify_dated_eod_with_original_rules(store, date, stock_code, quote, config):
    """Classify one dated EOD bar with the ORIGINAL approved v2 scope rules.

    Upper-limit detection uses the exact dated limit price:
        limit_price = pre_close * (1 + rate), rounded to 0.01
    with rate 5% (ST), 20% (CHINEXT/STAR), 10% otherwise. A non-positive
    authenticated return cannot be a positive upper limit. Anything
    unverifiable stays PENDING; nothing defaults to 0 or False.
    """
    d = day(date)
    c = code(stock_code)
    from core.approved_policy import scope_decision, exchange_board
    from decimal import Decimal, ROUND_HALF_UP
    calendar = _calendar(store, config)
    master = _master(store, config)
    ent = master['members'].get(c)
    out = {'code': c, 'board_count': None}
    if ent is None:
        out.update(scope_status='PENDING', reasons=['SECURITY_MASTER_MISSING'],
                   is_limit_up=None, name=None)
        out['evidence_id'] = digest({'date': d, 'code': c, 'scope_status': 'PENDING',
                                     'reason': 'SECURITY_MASTER_MISSING'})
        return out
    if str(ent.get('type', '')) not in {'1','2','3'}:
        out.update(scope_status='PENDING', reasons=['SECURITY_TYPE_MISSING'],
                   is_limit_up=None, name=ent.get('name'))
        out['evidence_id'] = digest({'date':d,'code':c,'reason':'SECURITY_TYPE_MISSING'})
        return out
    if str(ent.get('type', '')) != '1':
        out.update(scope_status='EXCLUDED', reasons=['NON_STOCK_ENTITY'],
                   is_limit_up=None, name=ent.get('name'))
        out['evidence_id'] = digest({'date': d, 'code': c, 'scope_status': 'EXCLUDED',
                                     'reason': 'NON_STOCK_ENTITY',
                                     'entity_type': ent.get('type')})
        return out
    raw = quote.get('raw_row') or {}
    is_st = None
    if str(raw.get('isST','')).strip() in {'0','1'}:
        is_st = str(raw['isST']).strip() == '1'
    if is_st is None:
        out.update(scope_status='PENDING', reasons=['DATED_ST_STATUS_MISSING'],
                   is_limit_up=None, name=ent.get('name'))
        out['evidence_id'] = digest({'date':d,'code':c,'reason':'DATED_ST_STATUS_MISSING'})
        return out
    record = {
        'code': c, 'name': ent.get('name'), 'source_date': d,
        'market_board': exchange_board(c), 'is_st': is_st,
        'listing_date': ent.get('ipo_date'),
    }
    dec = scope_decision(record, d, calendar) if calendar else {
        'status': 'UNKNOWN', 'reasons': ['CALENDAR_UNVERIFIED']}
    out.update(scope_status=dec['status'], reasons=dec['reasons'],
               trading_day_ordinal=dec.get('trading_day_ordinal'),
               is_st=is_st, name=ent.get('name'))
    is_limit_up = None
    if dec['status'] == 'ELIGIBLE':
        close = number(quote.get('close'))
        pre = number(quote.get('pre_close'))
        pct = number(quote.get('pct_change'))
        if quote.get('trading_status') == 'TRADING' and finite(pct) and pct <= 0:
            # A zero/negative authenticated return cannot be a positive limit-up close.
            is_limit_up = False
        elif finite(pre) and finite(close) and pre > 0 and close > 0:
            board = exchange_board(c)
            rate = Decimal('0.05') if is_st else (
                Decimal('0.20') if board in ('CHINEXT_A', 'STAR_A') else Decimal('0.10'))
            lp = (Decimal(str(pre)) * (Decimal('1') + rate)).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP)
            is_limit_up = abs(round(close, 2) - float(lp)) < 1e-6
            out['pre_close'] = pre
            out['limit_price'] = float(lp)
        else:
            out['limit_state_reason'] = 'PRECLOSE_OR_CLOSE_MISSING_OR_UNVERIFIED'
    out['is_limit_up'] = is_limit_up
    out['evidence_id'] = digest({
        'date': d, 'code': c, 'scope': dec,
        'close': quote.get('close'), 'pre_close': quote.get('pre_close'),
        'pct_change': quote.get('pct_change'), 'is_st': is_st,
        'is_limit_up': is_limit_up, 'entity_type': ent.get('type'),
        'rule': RULE_VERSION,
    })
    return out


# --------------------------------------------------------------------------
# 3. pool_date_proof
# --------------------------------------------------------------------------
def pool_date_proof(store, envelope, config):
    """An old receipt for date D cannot authenticate a new response for D.

    Source parser must persist a bound native-date/full-response proof under
    pool_response_proof[envelope.evidence_id]. It is not a manual confirmation.
    Request date or unrelated legacy receipts never suffice.
    """
    d=day(envelope['request']['date']);eid=envelope.get('evidence_id')
    got=store.get('pool_response_proof',eid) if eid else None
    p=got['data'] if got else {}
    rows=envelope.get('rows',[])
    valid=(p.get('native_source_date')==d
           and p.get('response_evidence_id')==eid
           and p.get('rows_sha256')==digest(rows)
           and p.get('row_count')==len(rows)
           and p.get('complete') is True
           and p.get('proof_basis')=='NATIVE_RESPONSE_DATE_AND_PAGINATION'
           and bool(p.get('raw_response_evidence_id'))
           and bool(p.get('extractor_identity')))
    if not valid:
        return {'date':None,'complete':False,
                'reason':'RESPONSE_BOUND_NATIVE_DATE_AND_COMPLETENESS_REQUIRED'}
    # Locate the native response itself, not just a free-standing true flag.
    native=store.get('native_response',p['raw_response_evidence_id'])
    if not native or native['data'].get('response_evidence_id') != eid:
        return {'date':None,'complete':False,'reason':'NATIVE_RESPONSE_RECORD_NOT_FOUND'}
    return {'date':d,'complete':True,'evidence_id':got['id'],
            'source':'RESPONSE_BOUND_NATIVE_PROOF','raw_response_revision':native['id']}


# --------------------------------------------------------------------------
# 4. refresh_source_records_to_db
# --------------------------------------------------------------------------
def refresh_source_records_to_db(store, config):
    """Migrate every published legacy batch snapshot into canonical layers.

    Only published_days are authoritative one-time inputs. Each snapshot goes
    through ingest_dashboard (cohort + dated bars + legacy performance).
    Per-day failures are recorded as gaps and never abort other days.
    """
    from p50fix.ingest import ingest_dashboard
    db = _original_db_path(store, config)
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT p.trade_date,b.id,b.snapshot_json FROM published_days p "
        "JOIN batches b ON b.id=p.batch_id ORDER BY p.trade_date").fetchall()
    conn.close()
    ingested, gaps = [], []
    for r in rows:
        d = day(r['trade_date'])
        try:
            snap = json.loads(r['snapshot_json'])
            if day(snap.get('date')) != d:
                raise ValueError('snapshot date mismatch')
            res = ingest_dashboard(store, snap, {
                'kind': 'LEGACY_PUBLISHED_BATCH', 'table': 'batches',
                'batch_id': r['id'], 'requested_date': d})
            ingested.append({'date': d, 'batch_id': r['id'],
                             'imported_rows': res['dated_rows_imported'],
                             'cohort_issue': res['cohort_issue']})
        except Exception as exc:
            gaps.append({'date': d, 'batch_id': r['id'],
                         'error': str(exc)[:300]})
    return {'published_days': len(rows), 'ingested_days': len(ingested),
            'ingested': ingested, 'gaps': gaps,
            'source': 'LEGACY_PUBLISHED_BATCHES', 'original_tables_mutated': False}


# --------------------------------------------------------------------------
# 5. recompute_original_engines
# --------------------------------------------------------------------------
def recompute_original_engines(store, original, context):
    """Run a real host adapter, or return an explicitly non-recomputed archive.

    The implementation of original_engine_adapter belongs to the host project
    because its real engines were NOT supplied in this handoff. A callback
    invocation alone is never recorded as successful engine recomputation.
    """
    d=day(context['date'])
    try:
        _root,cfg=_load_cfg(store)
    except FileNotFoundError:
        cfg={}
    spec=cfg.get('original_engine_adapter')
    if spec:
        if spec.endswith(':recompute_original_engines'):
            raise RepairError('ORIGINAL_ENGINE_ADAPTER_RECURSION')
        from p50fix.pipeline import plugin
        from inspect import getsourcefile
        import hashlib
        fun=plugin(spec)
        before=digest(original)
        result=fun(store,copy.deepcopy(original),copy.deepcopy(context))
        if not isinstance(result,dict) or day(result.get('date',''))!=d:
            raise RepairError('HOST_ENGINE_DATE_OR_SCHEMA_MISMATCH')
        if result.get('emotion',{}).get('score_source') in {
            'ORIGINAL_SNAPSHOT_NOT_RECOMPUTED','ARCHIVE_ONLY'}:
            raise RepairError('ARCHIVE_CANNOT_CLAIM_RECOMPUTATION')
        # A real recomputation that is still input-pending keeps the archived
        # original score only as an explicitly-labelled comparison, never as
        # a verified current score.
        emo=result.setdefault('emotion',{})
        if emo.get('score') is None:
            orig_emo=(original or {}).get('emotion') or {}
            if 'snapshot_score' not in emo and orig_emo.get('score') is not None:
                emo['snapshot_score']=orig_emo['score']
            emo.setdefault('score_status','RECOMPUTE_INPUT_GAP')
            emo.setdefault('snapshot_status','ORIGINAL_ARCHIVE_COMPARISON_ONLY')
        source_file=getsourcefile(fun)
        _receipt=result.pop('_host_engine_receipt',{})
        result['_host_engine_receipt']={
            'status':'RECOMPUTED','adapter':spec,
            'code_sha256':hashlib.sha256(Path(source_file).read_bytes()).hexdigest() if source_file else None,
            'input_sha256':digest(context),'original_sha256':before,
            'requires_host_input_output_verification':True}
        if _receipt.get('original_metrics_rejoined'):
            result['_host_engine_receipt']['original_metrics_rejoined']=_receipt['original_metrics_rejoined']
        return result
    result=copy.deepcopy(original) if original else {
        'date':d,'emotion':{},'input_evidence':{},'pool':{'tomorrow':[]},
        'limit':{},'market':{},'ladder':{},'leader':{}}
    result['date']=d
    emo=result.setdefault('emotion',{})
    if 'snapshot_score' not in emo:emo['snapshot_score']=emo.get('score')
    emo['score']=None
    emo['score_source']='ARCHIVE_ONLY'
    emo['score_status']='ORIGINAL_ENGINE_ADAPTER_REQUIRED'
    result['_host_engine_receipt']={'status':'NOT_RECOMPUTED',
        'reason':'ORIGINAL_ENGINE_ADAPTER_REQUIRED','date':d}
    result.setdefault('module_status',{})['original_engines']='NOT_RECOMPUTED'
    return result


# --------------------------------------------------------------------------
# 6. build_other_api_views
# --------------------------------------------------------------------------
def _op_store(store, config):
    """Open the ORIGINAL operational store (batches/reports/outcomes/...)."""
    root = _project_root(store)
    try:
        auto = json.loads((root / '5535_automation.json').read_text(encoding='utf-8-sig'))
        home = Path(auto.get('automation_home', '')).resolve()
    except Exception:
        home = None
    if home is None or not (home / 'automation5535').is_dir():
        raise RepairError('AUTOMATION_HOME_MISSING_FOR_OPERATIONAL_VIEWS')
    if str(home) not in sys.path:
        sys.path.insert(0, str(home))
    from automation5535.store import Store as OpStore
    db = _original_db_path(store, config)
    return OpStore(str(db))


def _op_view(key, fn):
    try:
        return fn()
    except RepairError:
        raise
    except Exception as exc:
        return {'error': True, 'error_type': 'MATERIALIZATION_FAILED',
                'error_message': str(exc)[:300], 'route': key}


def build_other_api_views(store):
    """Materialize every remaining /api/* route from the SAME SQLite store.

    Never reads CSV. Every branch either returns dated facts from the
    canonical/operational DB or an explicit error; nothing is fabricated.
    """
    root, cfg = _load_cfg(store)
    extras = {}

    def put(key, obj):
        if not key.startswith('/api/'):
            raise RepairError('INVALID_ROUTE_KEY:' + key)
        extras[key] = obj

    # ---- operational-store routes (automation5535 views) -----------------
    op = None
    try:
        op = _op_store(store, cfg)
        import automation5535.history_db as H
        from automation5535.smash_history_view import history_inspection
        from automation5535.money_smash_metrics import view as money_view
        from automation5535.closed_loop_view import get_closed_loop
    except Exception as exc:
        op_error = {'error': True, 'error_type': 'AUTOMATION_HOME_BLOCKED',
                    'error_message': str(exc)[:300]}
        put('/api/pipeline/status', op_error)
        put('/api/history', op_error)
        put('/api/history/imported', op_error)
        put('/api/backtest', op_error)
        op = None

    if op is not None:
        try:
            dates = H.available_dates(op)
        except Exception:
            dates = []
        latest = dates[0] if dates else None

        def history_view():
            h, _s = H.series(op, latest or '', limit=0)
            return {'history': h, 'source': 'SQLITE_OPERATIONAL_STORE'}
        put('/api/history', _op_view('/api/history', history_view))

        def inv_view():
            return H.inventory(op)
        put('/api/history/imported', _op_view('/api/history/imported', inv_view))

        def pipeline_status():
            j = op.latest_job() if hasattr(op, 'latest_job') else None
            view = None
            if j and j.get('status') != 'RUNNING' and j.get('batch_id'):
                jb = op.get_batch(batch_id=j['batch_id']) if hasattr(op, 'get_batch') else None
                if jb:
                    try:
                        snap = json.loads(jb['snapshot_json'])
                    except Exception:
                        snap = {}
                    view = {'date': snap.get('date', j.get('requested_date')),
                            'emotion_score': (snap.get('emotion') or {}).get('score'),
                            'smash_score': (snap.get('smash') or {}).get('score'),
                            'highest_board': (snap.get('smash') or {}).get('highest_board'),
                            'limit_up_count': (snap.get('limit') or {}).get('up'),
                            'limit_down_count': (snap.get('limit') or {}).get('down'),
                            'status': 'GENERATED_NOT_STRATEGY_ACCEPTANCE' if jb.get('quality_status') == 'VALID_MARKET_INPUT' else 'DATA_PENDING'}
            return {'running': bool(j and j['status'] == 'RUNNING'),
                    'progress': j['status'] if j else 'NOT_RUN',
                    'result': view, 'error': j.get('error') if j else None,
                    'job': j, 'database': str(op.path),
                    'dates': dates, 'data_validity_not_equal_job_success': True,
                    'formal_strategy': 'NOT_ENABLED'}
        put('/api/pipeline/status', _op_view('/api/pipeline/status', pipeline_status))

        for d in ([latest] if latest else []) + ([None] if not dates else []):
            for route, fn in [
                ('/api/smash/history', lambda d=d: history_inspection(op, d or latest or '')),
                ('/api/research/money-effect', lambda d=d: money_view(op, d or None)),
                ('/api/research/closed-loop', lambda d=d: get_closed_loop(op, d or None, None)),
            ]:
                if d:
                    put(route + '|date=' + d, _op_view(route, fn))
                else:
                    put(route, _op_view(route, fn))

        def research_daily():
            b = op.get_batch(latest) if latest else None
            if not b:
                return {'error': True, 'error_type': 'NO_COMMITTED_DATABASE_BATCH',
                        'date': latest, 'formal_strategy': 'NOT_ENABLED'}
            bid = b['id']
            with op.conn(True) as c:
                r = c.execute("SELECT payload_json FROM reports WHERE batch_id=? AND kind='day_summary'",
                              (bid,)).fetchone()
            return {'batch_id': bid,
                    'summary': json.loads(r[0]) if r else {},
                    'candidates': op.rows(bid, 'candidates') if hasattr(op, 'rows') else [],
                    'results': op.rows(bid, 'research_results') if hasattr(op, 'rows') else [],
                    'factors': op.rows(bid, 'factor_results') if hasattr(op, 'rows') else [],
                    'observations': op.rows(bid, 'observations') if hasattr(op, 'rows') else []}

        def research_report():
            b = op.get_batch(latest) if latest else None
            if not b:
                return {'error': True, 'error_type': 'NO_COMMITTED_DATABASE_BATCH', 'date': latest}
            text = op.get_report(b['id']) if hasattr(op, 'get_report') else None
            if not text:
                return {'error': True, 'error_type': 'RESEARCH_NOT_GENERATED',
                        'batch_id': b['id'], 'status': b.get('research_status')}
            return {'report': text, 'batch_id': b['id'], 'date': b['trade_date'],
                    'source': 'SQLITE_OPERATIONAL_STORE'}

        def research_outcomes():
            b = op.get_batch(latest) if latest else None
            if not b:
                return {'error': True, 'error_type': 'NO_COMMITTED_DATABASE_BATCH', 'date': latest}
            with op.conn(True) as c:
                rows = [json.loads(r[0]) for r in c.execute(
                    "SELECT payload_json FROM outcomes WHERE t_batch_id=? ORDER BY outcome_date,code",
                    (b['id'],))]
            return {'t_batch_id': b['id'], 'records': rows,
                    'note': 'T+1 stored separately; no T feature rewrites'}

        for suffix, fn in [('', lambda: research_daily()),
                           ('|date=' + latest, lambda: research_daily()) if latest else None]:
            if suffix == '':
                put('/api/research/daily', _op_view('/api/research/daily', fn))
            elif fn is not None:
                put('/api/research/daily' + suffix, _op_view('/api/research/daily', fn))
        for suffix, fn in [('', lambda: research_report()),
                           ('|date=' + latest, lambda: research_report()) if latest else None]:
            if suffix == '':
                put('/api/research/report', _op_view('/api/research/report', fn))
            elif fn is not None:
                put('/api/research/report' + suffix, _op_view('/api/research/report', fn))
        for suffix, fn in [('', lambda: research_outcomes()),
                           ('|date=' + latest, lambda: research_outcomes()) if latest else None]:
            if suffix == '':
                put('/api/research/outcomes', _op_view('/api/research/outcomes', fn))
            elif fn is not None:
                put('/api/research/outcomes' + suffix, _op_view('/api/research/outcomes', fn))

        # /api/backtest: rebuild from DB-only dated history (no CSV).
        def backtest_view():
            try:
                import pandas as pd
                from reports.backtest_engine import (calc_overview, calc_emotion_zones,
                                             calc_smash_backtest,
                                             calc_highest_board_backtest,
                                             calc_trend_data)
            except Exception as exc:
                return {'error': True, 'error_type': 'BACKTEST_DEPS_UNAVAILABLE',
                        'error_message': str(exc)[:200]}
            h, s = H.series(op, latest or '', limit=0)
            if not h:
                return {'status': 'DATA_PENDING', 'reason': 'NO_DATED_HISTORY_SERIES'}
            df_e = pd.DataFrame(h)
            df_s = pd.DataFrame(s)
            rename = {'limit_up': 'limit_up_count', 'limit_down': 'limit_down_count'}
            for a, b in rename.items():
                if a in df_e.columns and b not in df_e.columns:
                    df_e[b] = df_e[a]
            try:
                return {
                    'overview': calc_overview(df_e),
                    'emotion_zones': calc_emotion_zones(df_e),
                    'smash_backtest': calc_smash_backtest(df_s, df_e),
                    'highest_board_backtest': calc_highest_board_backtest(df_e),
                    'trend': calc_trend_data(df_e, df_s),
                    'sample_warning': len(df_e) < 20,
                    'source': 'SQLITE_ONLY',
                }
            except Exception as exc:
                return {'status': 'DATA_PENDING', 'reason': 'BACKTEST_CALC_FAILED: ' + str(exc)[:200]}
        put('/api/backtest', _op_view('/api/backtest', backtest_view))

    # ---- project read-only JSON/DB routes (same logic as web_app) --------
    try:
        from snapshot_loader import get_config, load_validation_data
    except Exception:
        get_config = load_validation_data = None

    def validation_view(date_arg=None):
        if get_config is None:
            return {'error': True, 'error_type': 'SNAPSHOT_LOADER_MISSING'}
        data, _st, _err = load_validation_data(get_config(), date_arg)
        return data
    put('/api/validation', _op_view('/api/validation', lambda: validation_view(None)))
    try:
        put('/api/validation/config', _op_view(
            '/api/validation/config',
            lambda: {'status': 'OK',
                     'config': get_config().to_dict() if hasattr(get_config(), 'to_dict') else None}))
    except Exception as exc:
        put('/api/validation/config', {'error': True, 'error_type': 'CONFIG_READ_FAILED',
                                       'error_message': str(exc)[:200]})
    for d in ['20260915', '20260911', '20260904', '20260909']:
        put('/api/validation|date=' + d,
            _op_view('/api/validation|date=' + d, lambda d=d: validation_view(d)))

    def cycle_view(date_arg=None):
        from cycle_theme_view import load_cycle_theme_data
        view, st, errs = load_cycle_theme_data(requested_date=date_arg)
        if view.get('error'):
            view['_load_status'] = st
        return view
    put('/api/research/cycle-theme',
        _op_view('/api/research/cycle-theme', lambda: cycle_view(None)))
    for d in ['20260915', '20260911', '20260909']:
        put('/api/research/cycle-theme|date=' + d,
            _op_view('/api/research/cycle-theme|date=' + d, lambda d=d: cycle_view(d)))

    def ledger_view(date_arg=None):
        from evidence.evidence_ledger import build_ledger_view, LedgerRootError
        project_root = str(_project_root(store))
        records_path = str(Path(project_root) / 'research_evidence' / 'records.json')
        try:
            return build_ledger_view(project_root=project_root, records_path=records_path)
        except LedgerRootError as exc:
            return {'error': True, 'error_type': exc.error_type,
                    'error_message': exc.error_message}
    put('/api/research/evidence-ledger',
        _op_view('/api/research/evidence-ledger', lambda: ledger_view(None)))
    put('/api/research/evidence-ledger|date=20260904',
        _op_view('/api/research/evidence-ledger|date=20260904', lambda: ledger_view('20260904')))

    def theme_review_view(date_arg=None):
        from review_revision_view import (resolve_database_path, build_panel_for_target,
                                          scope_is_target, latest_published_date,
                                          TARGET_BASE_BATCH, TARGET_TRADE_DATE)
        from review_revision_sqlite import ReviewNotFound, RepositoryError
        db = resolve_database_path(str(Path(_project_root(store)) / 'web_app.py'))
        scope_date = date_arg or latest_published_date(db)
        if not scope_is_target(TARGET_BASE_BATCH, scope_date):
            return {'state': 'NO_REVISION_FOR_SCOPE', 'date': scope_date,
                    'message': '该展示范围没有对应的题材复核修订；不展示其他日期的结果作为兜底'}
        try:
            model, trace, scope = build_panel_for_target(db)
            return {'state': 'READY', 'schema': 'P48_THEME_REVIEW_PANEL_V1',
                    'date': scope_date, 'scope': scope, 'panel': model,
                    'read_trace': trace}
        except ReviewNotFound as exc:
            return {'state': 'NOT_FOUND', 'error': str(exc)}
        except (RepositoryError, Exception) as exc:
            return {'state': 'ERROR', 'error_type': type(exc).__name__, 'error': str(exc)}
    put('/api/research/theme-review',
        _op_view('/api/research/theme-review', lambda: theme_review_view(None)))
    put('/api/research/theme-review|date=20260914',
        _op_view('/api/research/theme-review|date=20260914', lambda: theme_review_view('20260914')))

    return extras
