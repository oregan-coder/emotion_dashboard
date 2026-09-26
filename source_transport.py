"""Observe the *existing* AKShare call; never infer quote dates or change samples.

Only a counted Sina GET page returning HTTP 200 with null/[] is retried, once,
using the identical prepared request. No 401/403/429 retries, cookies, alternate
providers, new quote values, or cross-batch merges. Other threads pass through.
Transport coverage != approved-market coverage != date/finality validation.
"""
from __future__ import annotations
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, parse_qsl
import hashlib
import importlib.metadata
import inspect
import json
import math
import re
import threading
import time
import pandas as pd
import requests

_LOCK = threading.RLock()
_OWNER = ContextVar('5535_source_transport_owner', default=None)
_COUNT_PATH = '/quotes_service/api/json_v2.php/Market_Center.getHQNodeStockCount'
_PAGE_PATH = '/quotes_service/api/json_v2.php/Market_Center.getHQNodeData'
_SINA = 'vip.stock.finance.sina.com.cn'
_POOL_PATHS = {'/getTopicZTPool', '/getTopicDTPool', '/getTopicZBPool', '/getYesterdayZTPool'}
_SAFE_QUERY = {'date','page','num','sort','asc','node','pagesize','Pageindex','pn','pz','fs','fid'}

def _positive_integer(value, allow_zero=False):
    if isinstance(value, bool) or not re.fullmatch(r'\d+', str(value)):
        return None
    n = int(value)
    return n if n >= (0 if allow_zero else 1) else None

def _code(record):
    if not isinstance(record, dict): return None
    value = str(record.get('code', record.get('c', record.get('symbol', ''))))
    value = re.sub(r'^(sh|sz|bj)', '', value, flags=re.I)
    return value if re.fullmatch(r'\d{6}', value) else None

def _payload(response):
    try: return response.json()
    except (ValueError, TypeError): return None

def _observation(request, response):
    u = urlsplit(request.url)
    q = dict(parse_qsl(u.query))
    obj = _payload(response)
    item = {'host':u.hostname, 'path':u.path,
            'query':{k:v for k,v in q.items() if k in _SAFE_QUERY},
            'http_status':response.status_code,
            'captured_at_utc':datetime.now(timezone.utc).isoformat(),
            'response_bytes':len(response.content),
            'response_sha256':hashlib.sha256(response.content).hexdigest(),
            'date_verified':False, 'approved_scope_complete':False}
    rows = None
    if u.hostname == _SINA and u.path == _COUNT_PATH:
        item['kind'] = 'SINA_COUNT'
        item['provider_total'] = _positive_integer(obj, allow_zero=True)
    elif u.hostname == _SINA and u.path == _PAGE_PATH:
        item['kind'] = 'SINA_PAGE'
        item['page'] = _positive_integer(q.get('page'))
        item['page_size'] = _positive_integer(q.get('num'))
        rows = obj if isinstance(obj,list) else None
        item['empty_or_null'] = obj is None or obj == []
        item['payload_type'] = type(obj).__name__
    elif u.hostname == 'push2ex.eastmoney.com' and u.path in _POOL_PATHS:
        item['kind'] = 'EASTMONEY_POOL'
        data = obj.get('data') if isinstance(obj,dict) else None
        item['rc'] = obj.get('rc') if isinstance(obj,dict) else None
        item['upstream_data_is_null'] = isinstance(obj,dict) and obj.get('data') is None
        if isinstance(data,dict):
            item['provider_total'] = _positive_integer(data.get('tc'), allow_zero=True)
            item['qdate_raw'] = data.get('qdate')
            item['qdate_interpretation'] = 'RESPONSE_FIELD_NOT_ASSERTED_TO_BE_MEMBER_QUOTE_DATE'
            rows = data.get('pool') if isinstance(data.get('pool'),list) else None
    else:
        item['kind'] = 'OTHER_EXISTING_PROVIDER'
    if rows is not None:
        codes = [_code(x) for x in rows]
        valid = [x for x in codes if x is not None]
        item.update(row_count=len(rows), codes=valid, invalid_code_count=len(codes)-len(valid),
                    unique_code_count=len(set(valid)))
        ticks = [str(x['ticktime']) for x in rows if isinstance(x,dict) and isinstance(x.get('ticktime'),str)]
        if ticks:
            item['provider_tick_range'] = [min(ticks),max(ticks)]
            item['ticktime_is_time_only_not_trade_date'] = True
    return item

def summarize_transport(entries, frame_rows=None):
    """Pure replayable transport check; never returns production `complete=True`."""
    used = [x for x in entries if x.get('returned_to_fetcher')]
    totals = {x['provider_total'] for x in used if x.get('kind') == 'SINA_COUNT' and x.get('provider_total') is not None}
    pages = [x for x in used if x.get('kind') == 'SINA_PAGE']
    result = {'status':'NOT_OBSERVED','provider_collection_complete':False,
              'quote_date_verified':False,'approved_scope_complete':False,
              'quote_finality_verified':False,'observed_call_count':len(entries)}
    if pages:
        sizes = {x.get('page_size') for x in pages}
        total = next(iter(totals)) if len(totals)==1 else None
        size = next(iter(sizes)) if len(sizes)==1 else None
        expected = list(range(1, math.ceil(total/size)+1)) if total is not None and size else []
        # AKShare may request one trailing page when total is an exact page multiple.
        # A proven empty terminal page is not a missing in-range page.
        terminal = [x for x in pages if expected and x.get('page') == expected[-1]+1
                    and x.get('http_status') == 200 and x.get('row_count') == 0]
        active = [x for x in pages if x not in terminal]
        received = [x.get('page') for x in active]
        codes = [c for x in active for c in x.get('codes',[])]
        failures = [x.get('page') for x in active if x.get('http_status') != 200 or not x.get('row_count')
                    or x.get('invalid_code_count',0) or x.get('unique_code_count') != x.get('row_count')]
        wrong_size = [x.get('page') for x in active if x.get('page') in expected and
                      x.get('row_count') != min(size, total-(x['page']-1)*size)] if expected else []
        complete = (total is not None and bool(expected) and set(received)==set(expected)
                    and len(received)==len(set(received)) and len(terminal)<=1 and not failures and not wrong_size
                    and len({x.get('query',{}).get('node','hs_a') for x in used if x.get('kind') in ('SINA_COUNT','SINA_PAGE')})==1
                    and len(codes)==len(set(codes))==total
                    and (frame_rows is None or frame_rows==total))
        result.update(status='COMPLETE_PROVIDER_COLLECTION_ONLY' if complete else 'INCOMPLETE_PROVIDER_COLLECTION',
                      provider_collection_complete=bool(complete),provider_total=total,page_size=size,
                      expected_pages=expected,received_pages=received,terminal_empty_pages=[x['page'] for x in terminal],
                      missing_pages=sorted(set(expected)-set(received)),invalid_pages=sorted(set(failures+wrong_size),key=str),
                      provider_rows=sum(x.get('row_count',0) for x in pages),unique_codes=len(set(codes)),
                      duplicate_code_count=len(codes)-len(set(codes)),returned_frame_rows=frame_rows)
    else:
        pools = [x for x in used if x.get('kind')=='EASTMONEY_POOL']
        if pools:
            valid = all(x.get('http_status')==200 and x.get('rc')==0 and
                        x.get('row_count') is not None and x.get('provider_total')==x.get('row_count')==x.get('unique_code_count')
                        and x.get('invalid_code_count',0)==0 for x in pools)
            empty = valid and all(x['row_count']==0 for x in pools)
            result.update(status=('EMPTY_PROVIDER_COLLECTION_ONLY' if empty else 'COMPLETE_PROVIDER_COLLECTION_ONLY')
                          if valid else 'INCOMPLETE_PROVIDER_COLLECTION',
                          provider_collection_complete=bool(valid),
                          returned_frame_rows=frame_rows)
    result['note']='Transport/page consistency only; qdate/ticktime/request date do not establish approved-market quote date or scope.'
    return result

def fetch_with_transport(fetcher, *args, **kwargs):
    """Call the unchanged fetcher, retaining observations in DataFrame.attrs.

    Interface exceptions still propagate, so existing fallback behavior is not
    changed. The exception carries transport evidence for the existing catcher.
    """
    entries=[]; token_value=object()
    try: version=importlib.metadata.version('akshare')
    except importlib.metadata.PackageNotFoundError: version=None
    try:
        p=Path(inspect.getsourcefile(fetcher))
        identity={'path':str(p.resolve()),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    except (TypeError,OSError): identity={}
    info={'interface':getattr(fetcher,'__name__',type(fetcher).__name__),
          'module':getattr(fetcher,'__module__',None),'akshare_version':version,'implementation':identity,
          'scope':'EXISTING_FETCH_CALL_TRANSPORT_NOT_DATA_CALIBRATION','entries':entries,
          'retry_policy':'AT_MOST_ONE_IDENTICAL_GET_FOR_HTTP200_EMPTY_COUNTED_SINA_PAGE',
          'retries':0, 'date_verified':False,'complete':False}
    counter={'total':None}; failure=None; result=None
    with _LOCK:
        original=requests.Session.send
        owner_token=_OWNER.set(token_value)
        def traced(session, request, **kw):
            if _OWNER.get() is not token_value or request.method.upper()!='GET':
                return original(session,request,**kw)
            u=urlsplit(request.url)
            allowed=(u.hostname==_SINA and u.path in (_COUNT_PATH,_PAGE_PATH)) or (u.hostname=='push2ex.eastmoney.com' and u.path in _POOL_PATHS)
            if not allowed or kw.get('stream') or request.headers.get('Authorization') or request.headers.get('Cookie'):
                return original(session,request,**kw)
            # Bound the existing approved pool calls so a provider outage
            # cannot leave the UI job waiting indefinitely.
            kw.setdefault('timeout', 60)
            try: response=original(session,request,**kw)
            except Exception as exc:
                entries.append({'kind':'REQUEST_ERROR','host':u.hostname,'path':u.path,
                                'error_type':type(exc).__name__,'returned_to_fetcher':False})
                raise
            try: entry=_observation(request,response)
            except Exception as exc:
                entries.append({'kind':'OBSERVER_ERROR','error_type':type(exc).__name__,'returned_to_fetcher':True})
                return response
            entry['attempt']=1;entry['returned_to_fetcher']=True;entries.append(entry)
            if entry.get('kind')=='SINA_COUNT' and response.status_code==200:
                counter['total']=entry.get('provider_total')
            p=entry.get('page');n=entry.get('page_size');total=counter['total']
            retry=(entry.get('kind')=='SINA_PAGE' and response.status_code==200
                   and entry.get('empty_or_null') and p and n and total is not None and 0<(p-1)*n+1<=total)
            # Non-JSON/error/challenge bodies are NOT bypassed as empty pages.
            retry=bool(retry and (not response.content.strip() or response.content.strip() in (b'null',b'[]')))
            if retry:
                info['retries']+=1
                time.sleep(0.25)
                try:
                    second=original(session,request,**kw)
                    second_entry=_observation(request,second)
                    second_entry.update(attempt=2,returned_to_fetcher=True,retry_of=len(entries)-1)
                    entry['returned_to_fetcher']=False;entries.append(second_entry)
                    return second
                except Exception as exc:
                    entries.append({'kind':'RETRY_ERROR','host':u.hostname,'path':u.path,'page':p,
                                    'error_type':type(exc).__name__,'returned_to_fetcher':False})
                    # Do not invent rows or alter the first provider response.
                    return response
            return response
        requests.Session.send=traced
        try: result=fetcher(*args,**kwargs)
        except Exception as exc: failure=exc
        finally:
            if requests.Session.send is traced: requests.Session.send=original
            _OWNER.reset(owner_token)
    info['summary']=summarize_transport(entries,len(result) if isinstance(result,pd.DataFrame) else None)
    if failure is not None:
        info['fetch_status']='ERROR';info['error_type']=type(failure).__name__
        setattr(failure,'source_transport_evidence',info)
        raise failure
    info['fetch_status']='RETURNED_DATAFRAME' if isinstance(result,pd.DataFrame) else 'INVALID_RETURN_TYPE'
    if isinstance(result,pd.DataFrame): result.attrs['source_transport']=info
    return result
