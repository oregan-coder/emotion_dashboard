"""Optional, consent-gated SAME EASTMONEY candidate daily-bar crosscheck.

Never replaces a price/volume/score, verifies a full market, or selects a theme.
A dated daily bar, post-close ORIGINAL pool capture, actual membership and exact
price agreement are all needed. Timestamp/qdate/request date alone is not proof.
The supplement and comparison outcomes are saved by the existing pipeline.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
import hashlib
import json
import re
import time

CN = timezone(timedelta(hours=8))
SCHEMA = '5535_CANDIDATE_SAME_PROVIDER_CHECK_V1'
POLICY_SCHEMA = '5535_SAME_PROVIDER_CHECK_CONSENT_V1'
METHOD = 'EASTMONEY_DAILY_1D_UNADJUSTED_AND_CAPTURED_POOL_EXACT_PRICE'
URL = 'https://push2his.eastmoney.com/api/qt/stock/kline/get'
FIELDS = ['date','open','close','high','low','volume_lots','amount',
          'amplitude','change_pct','change','turnover_pct']


def stamp(value):
    if not isinstance(value, str):
        return None
    try:
        d = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return d.astimezone(CN) if d.tzinfo is not None else None
    except ValueError:
        return None


def day(value):
    if not isinstance(value, str):
        return None
    s = value.replace('-', '')
    if not re.fullmatch(r'\d{8}', s):
        return None
    try:
        return datetime.strptime(s, '%Y%m%d').strftime('%Y%m%d')
    except ValueError:
        return None


def cents(value):
    """Exact declared CNY tick; rejects malformed/more-than-cent input. No tolerance calibration."""
    if value is None or isinstance(value, bool) or type(value).__name__ == 'bool_':
        return None
    try:
        v = Decimal(str(value))
        if not v.is_finite() or v <= 0:
            return None
        c = v * 100
        # The input pool divides integer thousandths into IEEE float. Limit
        # acceptance to machine-noise (<1e-7 cent), not a market price tolerance.
        n = c.to_integral_value()
        if abs(c-n) > Decimal('0.0000001'):
            return None
        return int(n)
    except (InvalidOperation, ValueError, TypeError):
        return None


def numeric(value):
    if value is None or isinstance(value, bool) or type(value).__name__ == 'bool_':
        return None
    try:
        v = Decimal(str(value))
        return float(v) if v.is_finite() else None
    except (ValueError, TypeError, InvalidOperation):
        return None


def rows(frame):
    if frame is None or not hasattr(frame, 'to_dict'):
        return []
    return frame.to_dict('records')


def code(row):
    raw = str(row.get('代码', row.get('code', '')))
    raw = re.sub(r'^(sh|sz)', '', raw)
    return raw if re.fullmatch(r'\d{6}', raw) else None


def policy_for(project):
    p = Path(project)/'data'/'same_provider_candidate_check.json'
    if not p.is_file():
        return {'enabled': False, 'status': 'AWAITING_EXPLICIT_USER_ENABLE'}
    try:
        obj = json.loads(p.read_text(encoding='utf-8-sig'))
    except (ValueError, OSError) as exc:
        return {'enabled': False, 'status':'INVALID_POLICY', 'error':str(exc)}
    valid = (obj.get('schema') == POLICY_SCHEMA and obj.get('enabled') is True
             and obj.get('method') == METHOD and stamp(obj.get('approved_at')) is not None
             and obj.get('approval_action') == 'ENABLE_SAME_PROVIDER_VALIDATION'
             and obj.get('replace_original_prices') is False)
    return {**obj, 'enabled':valid, 'status':'ENABLED' if valid else 'DISABLED_OR_INVALID'}


def request_bars(symbol, board, begin, end, *, session=None, timeout=(4, 8),
                 max_attempts=2, sleep=None):
    """At most two IDENTICAL GETs for transient transport failures.

    Keeps proxy/environment/TLS settings; never falls back to direct networking,
    alternate host, cookies, authentication or adjusted data. No retry for
    401/403/407/429, redirects, certificate errors, malformed or empty data.
    Success is still RETURNED_UNVALIDATED and must pass evaluate_candidate.
    A server Retry-After stops this call rather than retrying earlier than asked.
    """
    import requests
    market = {'SSE_MAIN_A':1,'STAR_A':1,'SZSE_MAIN_A':0,'CHINEXT_A':0}.get(board)
    if (not re.fullmatch(r'\d{6}', str(symbol)) or market is None
        or not day(begin) or not day(end) or day(begin) > day(end)):
        return {'status':'IDENTITY_OR_DATES_UNKNOWN', 'symbol':symbol}
    if type(max_attempts) is not int or max_attempts not in (1, 2):
        raise ValueError('AT_MOST_TWO_IDENTICAL_REQUEST_ATTEMPTS')
    pause = time.sleep if sleep is None else sleep
    params = {'fields1':'f1,f2,f3,f4,f5,f6',
        'fields2':'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
        'klt':'101','fqt':'0','secid':f'{market}.{symbol}',
        'beg':begin,'end':end,'ut':'7eea3edcaed734bea9cbfc24409ed989'}
    base = {'symbol':symbol,'url':URL,'params':params,
        'provider':'EASTMONEY','price_replacement':False,'requested_dates':[begin,end]}
    attempts = []
    for attempt_no in range(1, max_attempts + 1):
        # For our own session, discard the failed connection pool. The new
        # session uses the SAME Requests environment/proxy and TLS policy.
        own = session is None
        client = requests.Session() if own else session
        response = None
        result = dict(base, status='ERROR')
        retryable = False
        try:
            response = client.get(URL, params=dict(params), timeout=timeout,
                                  allow_redirects=False)
            raw = response.content
            result.update(captured_at=datetime.now(CN).isoformat(),
                http_status=response.status_code,response_bytes=len(raw),
                response_sha256=hashlib.sha256(raw).hexdigest())
            if response.status_code != 200:
                result['status'] = 'HTTP_NOT_200'
                retryable = response.status_code in (502,503,504)
                headers = getattr(response,'headers',{}) or {}
                retry_after = headers.get('Retry-After')
                if retry_after is not None:
                    result['retry_after_present'] = True
                    result['retry_deferred_to_later_collection'] = True
                    retryable = False
            elif not raw.strip():
                result['status'] = 'EMPTY_RESPONSE'
            else:
                try:
                    result['payload'] = response.json()
                    result['status'] = 'RETURNED_UNVALIDATED'
                except (ValueError, TypeError) as exc:
                    result.update(status='INVALID_JSON',error_type=type(exc).__name__,
                                  error='Response was not valid JSON')
        except Exception as exc:
            # SSLError derives from ConnectionError; it is NOT transient here.
            retryable = (isinstance(exc,(requests.exceptions.ConnectionError,
                                         requests.exceptions.Timeout))
                         and not isinstance(exc,requests.exceptions.SSLError))
            error = re.sub(r'(https?://)[^/@\s]+:[^/@\s]+@',
                           r'\1[REDACTED]@',str(exc))
            result.update(status='REQUEST_ERROR',error_type=type(exc).__name__,
                          error=error,captured_at=datetime.now(CN).isoformat())
        finally:
            if response is not None and callable(getattr(response,'close',None)):
                response.close()
            if own:
                client.close()
        attempts.append({**{k:v for k,v in result.items() if k!='payload'},
                         'attempt':attempt_no,'retryable_transport_error':retryable})
        if not retryable or attempt_no == max_attempts:
            break
        pause(1.0)
    result.update(attempt_count=len(attempts),attempts=attempts,
        retry_policy='MAX_ONE_IDENTICAL_GET_RETRY_FOR_TRANSIENT_TRANSPORT_ONLY',
        proxy_policy='UNCHANGED_NO_DIRECT_FALLBACK',tls_verification_disabled=False)
    return result


def parse_bars(receipt, symbol):
    """Requires response identity; request `symbol` is never inserted as response identity."""
    problems = []
    if receipt.get('status') != 'RETURNED_UNVALIDATED' or receipt.get('http_status') != 200:
        status = str(receipt.get('status','UNKNOWN'))
        error_type = str(receipt.get('error_type',''))
        root = ('DAILY_BAR_REQUEST_ERROR:' + error_type if status == 'REQUEST_ERROR'
                and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', error_type)
                else 'DAILY_BAR_TRANSPORT_STATUS:' + status[:64])
        return {}, ['DAILY_BAR_NOT_RETURNED', root]
    req = receipt.get('params',{})
    if receipt.get('url') != URL or req.get('klt') != '101' or req.get('fqt') != '0':
        return {}, ['WRONG_DAILY_BAR_CONTRACT']
    payload = receipt.get('payload')
    data = payload.get('data') if isinstance(payload,dict) and payload.get('rc') == 0 else None
    if not isinstance(data,dict) or str(data.get('code','')) != symbol:
        return {}, ['DAILY_BAR_RESPONSE_IDENTITY_MISMATCH']
    expected_secid = str(req.get('secid',''))
    if not expected_secid.endswith('.'+symbol):
        return {}, ['DAILY_BAR_REQUEST_IDENTITY_MISMATCH']
    if data.get('market') is not None and str(data['market']) != expected_secid.split('.')[0]:
        return {}, ['DAILY_BAR_RESPONSE_MARKET_MISMATCH']
    bars = data.get('klines')
    if not isinstance(bars,list) or not bars:
        return {}, ['DAILY_BAR_EMPTY']
    out = {}
    for raw in bars:
        if not isinstance(raw,str) or len(raw.split(',')) != len(FIELDS):
            problems.append('DAILY_BAR_FIELD_COUNT'); continue
        row = dict(zip(FIELDS, raw.split(',')))
        d = day(row['date'])
        if not d or not day(req.get('beg')) or not day(req.get('end')) or not req['beg'] <= d <= req['end']:
            problems.append('DAILY_BAR_DATE_OUT_OF_REQUEST'); continue
        if d in out:
            problems.append('DAILY_BAR_DUPLICATE_DATE'); continue
        ps = [cents(row[k]) for k in ('open','close','high','low')]
        if any(v is None for v in ps) or ps[2] < max(ps[0],ps[1],ps[3]) or ps[3] > min(ps[0],ps[1]):
            problems.append('DAILY_BAR_OHLC_INVALID'); continue
        row['raw'] = raw
        out[d] = row
    return out, problems


def pool_proof(frame, expected_path, requested, *, response_day=None):
    """Transport provenance check, not a full scope assertion.
    response_day is used ONLY together with a separately dateful exact OHLC match.
    A historical pool's qdate being current does not give it a historical quote date.
    """
    attrs = getattr(frame,'attrs',{}) or {}
    transport = attrs.get('source_transport') or {}
    valid = [e for e in transport.get('entries',[]) if e.get('returned_to_fetcher') is True
        and e.get('kind') == 'EASTMONEY_POOL' and e.get('path') == expected_path]
    if len(valid) != 1:
        return None, ['POOL_CAPTURE_NOT_UNIQUE']
    e = valid[0]; when = stamp(e.get('captured_at_utc'))
    d = day(requested)
    if (e.get('host')!='push2ex.eastmoney.com' or e.get('http_status')!=200 or e.get('rc')!=0
        or e.get('query',{}).get('date')!=d or e.get('invalid_code_count')!=0):
        return None, ['POOL_RESPONSE_OR_REQUEST_INVALID']
    if e.get('row_count')!=e.get('unique_code_count') or not isinstance(e.get('codes'),list):
        return None,['POOL_ROWS_NOT_IDENTIFIABLE']
    if when is None or when.strftime('%Y%m%d') < d or (when.strftime('%Y%m%d')==d and when.hour<15):
        return None,['ORIGINAL_POOL_CAPTURE_NOT_AFTER_CLOSE']
    if response_day is not None and str(e.get('qdate_raw')) != response_day:
        return None,['POOL_RESPONSE_DAY_NOT_ALIGNED']
    if response_day is not None and when.strftime('%Y%m%d') != response_day:
        return None,['POOL_CAPTURE_DAY_NOT_ALIGNED']
    return e, []


def evaluate_candidate(symbol, current_row, previous_row, performance_row,
                       frames, bar_receipt, observation, previous, calendar):
    """Verifies ONLY this candidate's original pool record; never endorses other rows."""
    result={'code':symbol,'status':'DATA_PENDING','method':METHOD,'source_date':None,
        'date_verified':False,'closing_verified':False,'complete':False,
        'full_market_proven':False,'price_replacement':False,'issues':[],
        'current':{'status':'DATA_PENDING'},'previous':{'status':'DATA_PENDING'}}
    d,p=day(observation),day(previous)
    if not calendar.verified or calendar.previous(d)!=p:
        result['issues']=['CALENDAR_RELATION_UNPROVEN'];return result
    bars,issues=parse_bars(bar_receipt,symbol)
    result['issues']+=issues
    when=stamp(bar_receipt.get('captured_at'))
    if when is None or when.strftime('%Y%m%d') < d or (when.strftime('%Y%m%d')==d and when.hour<15):
        result['issues'].append('DAILY_PROOF_ACQUIRED_BEFORE_CLOSE_OR_UNKNOWN')
    bar=bars.get(d)
    entry,problems=pool_proof(frames.get('limit_up'),'/getTopicZTPool',d,response_day=d)
    result['issues']+=problems
    if not bar:result['issues'].append('CURRENT_EXPLICIT_DAILY_DATE_MISSING')
    if code(current_row or {})!=symbol:result['issues'].append('CURRENT_ROW_IDENTITY_MISSING')
    elif bar:
        if cents(current_row.get('最新价'))!=cents(bar['close']):result['issues'].append('CURRENT_CLOSE_PRICE_MISMATCH')
        # Return percentage is not rounded/calibrated/replaced: price match only.
        if cents(bar['close']) is None:result['issues'].append('CURRENT_CLOSE_INVALID')
    if entry and symbol not in entry.get('codes',[]):result['issues'].append('CANDIDATE_ABSENT_FROM_CAPTURED_POOL')
    if result['issues']:return result
    result.update(status='VALID',source_date=d,date_verified=True,closing_verified=True,
        as_of=d[:4]+'-'+d[4:6]+'-'+d[6:]+'T15:00:00+08:00',
        available_at=max(stamp(entry['captured_at_utc']),when).isoformat())
    result['current']={'status':'VALID','source_date':d,'date_verified':True,'closing_verified':True,
        'close_limit_up':True,'open_at_limit_up':cents(bar['open'])==cents(bar['close']),
        'daily_open':bar['open'],'daily_close':bar['close'],
        'pool_response_sha256':entry.get('response_sha256'),
        'daily_response_sha256':bar_receipt.get('response_sha256'),
        'original_value_fields_unchanged':True}
    # For T-1 identity/membership, additionally require today's *yesterday* pool
    # to explicitly identify the same member. The history qdate alone is not used.
    prev_issues=[]
    pb=bars.get(p)
    if not pb:prev_issues.append('PREVIOUS_EXPLICIT_DAILY_DATE_MISSING')
    he,hi=pool_proof(frames.get('previous_limit_up'),'/getTopicZTPool',p)
    pe,pi=pool_proof(frames.get('previous_pool_performance'),'/getYesterdayZTPool',d,response_day=d)
    prev_issues+=hi+pi
    if code(previous_row or {})!=symbol or code(performance_row or {})!=symbol:
        prev_issues.append('PREVIOUS_MEMBER_CROSSCHECK_MISSING')
    elif pb:
        if cents(previous_row.get('最新价'))!=cents(pb['close']):prev_issues.append('PREVIOUS_CLOSE_PRICE_MISMATCH')
        if cents(performance_row.get('最新价'))!=cents(bar['close']):prev_issues.append('YESTERDAY_PERFORMANCE_CURRENT_PRICE_MISMATCH')
        if previous_row.get('连板数')!=performance_row.get('昨日连板数'):
            prev_issues.append('PREVIOUS_BOARD_CROSSCHECK_MISMATCH')
    if he and symbol not in he.get('codes',[]):prev_issues.append('PREVIOUS_POOL_MEMBER_ABSENT')
    if pe and symbol not in pe.get('codes',[]):prev_issues.append('PERFORMANCE_MEMBER_ABSENT')
    if not prev_issues:
        result['previous']={'status':'VALID','source_date':p,'date_verified':True,'closing_verified':True,
            'close_limit_up':True,'open_at_limit_up':cents(pb['open'])==cents(pb['close']),
            'daily_open':pb['open'],'daily_close':pb['close'],
            'pool_response_sha256':he.get('response_sha256'),
            'membership_response_sha256':pe.get('response_sha256'),
            'daily_response_sha256':bar_receipt.get('response_sha256')}
    else:
        result['previous']['issues']=prev_issues
    return result


def collect_candidates(data, identities, calendar, *, policy=None, fetch=None, budget_seconds=90):
    project=Path(__file__).resolve().parent
    pol=policy if policy is not None else policy_for(project)
    out={'schema':SCHEMA,'method':METHOD,'policy':pol,'records':{},'requests':{},
        'price_replacement':False,'full_market_proven':False,'status':'DISABLED'}
    if pol.get('enabled') is not True:
        return out
    # Public union scope is explicitly approved and configured separately.
    from evidence.public_metric_evidence import enabled as public_enabled, collect_public
    if public_enabled(pol):
        return collect_public(data, identities, calendar, policy=pol, fetch=fetch,
                              budget_seconds=pol.get('public_budget_seconds', 480))
    from core.approved_policy import TradeCalendar
    cal=TradeCalendar(calendar.get('dates',[]),verified=calendar.get('verified') is True)
    d,p=day(data.date),day(data.previous_date)
    current=[r for r in rows(data.limit_up) if r.get('连板数')==2 and not isinstance(r.get('连板数'),bool)]
    def index(seq):
        ans={}; bad=set()
        for r in seq:
            c=code(r)
            if not c:continue
            if c in ans and ans[c]!=r:bad.add(c)
            ans[c]=r
        return {c:r for c,r in ans.items() if c not in bad},bad
    cmap,conflicts=index(current);pmap,_=index(rows(data.previous_limit_up));perf,_=index(rows(data.previous_pool_performance))
    frames={k:getattr(data,k,None) for k in ('limit_up','previous_limit_up','previous_pool_performance')}
    fetch=fetch or request_bars
    deadline=time.monotonic()+budget_seconds
    out.update(status='COMPLETE_WITH_PENDING',duplicate_conflicts=sorted(conflicts))
    for c,r in sorted(cmap.items()):
        identity=identities.get(c,{})
        if time.monotonic()>=deadline:
            out['records'][c]={'status':'DATA_PENDING','issues':['CHECK_TIME_BUDGET_EXHAUSTED']};continue
        if identity.get('identity_conflict') or identity.get('listing_date_conflict'):
            out['records'][c]={'status':'DATA_PENDING','issues':['MASTER_IDENTITY_CONFLICT']};continue
        try:
            captured=fetch(c,identity.get('market_board'),p,d)
        except Exception as exc:
            captured={'status':'REQUEST_ERROR','error':str(exc),'error_type':type(exc).__name__}
        out['requests'][c]=captured
        out['records'][c]=evaluate_candidate(c,r,pmap.get(c),perf.get(c),frames,captured,d,p,cal)
        if captured.get('http_status') in (401,403,429):
            out['status']='PROVIDER_ACCESS_LIMIT_STOPPED'
            for rest in sorted(set(cmap)-set(out['records'])):
                out['records'][rest]={'status':'DATA_PENDING','issues':['PROVIDER_ACCESS_LIMIT_STOPPED']}
            break
    out['validated_candidates']=sum(x.get('status')=='VALID' for x in out['records'].values())
    return out
