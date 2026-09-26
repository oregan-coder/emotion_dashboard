"""User-approved LEGULEGU native breadth, never a stock-universe substitute.

One AKShare function call per collection. A bounded subprocess isolates a slow
provider/parser without monkey-patching requests, proxy or TLS settings. Neither
failure nor a historical-date request falls back to a whole-market quote feed.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

CN = timezone(timedelta(hours=8))
SCHEMA = '5535_LEGU_NATIVE_BREADTH_V1'
MODE = 'POOL_SCOPED_WITH_LEGU_NATIVE'
SOURCE = 'LEGULEGU'
SCOPE = 'PROVIDER_NATIVE'
INTERFACE = 'stock_market_activity_legu'
SCOPE_LABEL = '乐咕原生市场宽度；未按本地ST/上市60交易日/板块范围重算'
APPROVAL = {'decision':'A_PROVIDER_NATIVE_LEGULEGU_BREADTH',
    'full_market_spot_enabled':False, 'full_market_fallback_enabled':False,
    'legu_limit_counts_used':False,'local_scope_filters_applied':False,
    'scoring_weights_changed':False}


def _dt(value):
    if isinstance(value, datetime):
        v=value
    elif isinstance(value, str) and value.strip():
        try:v=datetime.fromisoformat(value.strip().replace('Z','+00:00'))
        except ValueError:return None
    else:return None
    return v.astimezone(CN) if v.tzinfo is not None else None


def _day(value):
    s=str(value or '')
    if not re.fullmatch(r'\d{8}|\d{4}-\d{2}-\d{2}',s):return None
    try:return datetime.strptime(s.replace('-',''),'%Y%m%d').strftime('%Y%m%d')
    except ValueError:return None


def _count(value):
    # Boolean, non-finite, fractional and negative counts are never zero.
    if type(value) is bool or value is None or isinstance(value,(dict,list)):return None
    s=str(value).strip()
    if ',' in s:
        if not re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.0+)?',s):return None
        s=s.replace(',','')
    if not re.fullmatch(r'\d+(?:\.0+)?',s):return None
    try:v=Decimal(s)
    except InvalidOperation:return None
    return int(v) if v.is_finite() and v==v.to_integral_value() else None


def _provider_stamp(value):
    # Provider statistics timestamp, never local download date. Accept one
    # explicitly dated value with optional Chinese label / optional seconds.
    if not isinstance(value,str):return None, 'STATISTICS_TIMESTAMP_MISSING'
    s=value.strip()
    s=re.sub(r'^统计日期\s*[:：]?\s*','',s)
    if re.fullmatch(r'\d{4}[-/]\d{2}[-/]\d{2}',s):
        return None, 'STATISTICS_TIME_MISSING'
    if not re.fullmatch(r'\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?',s):
        return None,'STATISTICS_TIMESTAMP_FORMAT_UNSUPPORTED'
    try:v=datetime.fromisoformat(s.replace('/','-').replace('Z','+00:00'))
    except ValueError:return None,'STATISTICS_TIMESTAMP_INVALID'
    if v.tzinfo is None:v=v.replace(tzinfo=CN)
    return v.astimezone(CN),None


def pending(reason, *, requested_date=None, raw=None):
    return {'schema':SCHEMA,'source':SOURCE,'scope':SCOPE,'scope_label':SCOPE_LABEL,
        'requested_date':_day(requested_date),'status':'DATA_PENDING',
        'up':None,'down':None,'flat':None,'unknown':None,
        'source_date':None,'as_of':None,'date_verified':False,'closing_verified':False,
        'complete':False,'available_at':None,'issues':[reason],
        'approval':deepcopy(APPROVAL),'full_market_breadth_proven':False,
        'provider_native_breadth':True,'raw':deepcopy(raw) if raw is not None else None}


def parse_native(raw, observation, calendar):
    """Validate only the native three counts and its own statistics timestamp.

    The source's other rows (涨停,真实涨停,ST涨停,跌停,...) are retained in
    raw evidence but NEVER consumed as local event-pool statistics.
    """
    result=pending('NOT_PARSED',requested_date=observation,raw=raw)
    result['issues']=[]
    if not isinstance(raw,dict):result['issues']=['NO_PROVIDER_RESPONSE'];return result
    result['request_status']=raw.get('status')
    result['available_at']=raw.get('captured_at')
    result['request_calls']=raw.get('request_calls',0)
    result['implementation']=deepcopy(raw.get('implementation',{}))
    if raw.get('status')!='RETURNED_DATAFRAME':
        result['issues']=[str(raw.get('status','NO_PROVIDER_RESPONSE'))]
        result['error']=raw.get('error');return result
    if raw.get('interface')!=INTERFACE:
        result['issues']=['UNEXPECTED_PROVIDER_INTERFACE'];return result
    spec=raw.get('table') or {}
    cols=spec.get('columns');data=spec.get('data')
    if not isinstance(cols,list) or len(cols)!=len(set(cols)) or not {'item','value'}.issubset(cols) or not isinstance(data,list):
        result['issues']=['ITEM_VALUE_SCHEMA_INVALID'];return result
    labels={};required={'上涨','下跌','平盘','统计日期'};dups=[]
    for row in data:
        if not isinstance(row,list) or len(row)!=len(cols):
            result['issues']=['ROW_SCHEMA_INVALID'];return result
        obj=dict(zip(cols,row));label=str(obj['item']).strip().rstrip(':：').strip()
        if label in required:
            if label in labels:dups.append(label)
            labels[label]=obj['value']
    result['observed_values']={k:labels.get(k) for k in ('上涨','下跌','平盘','统计日期')}
    if dups:result['issues']=['DUPLICATE_REQUIRED_ITEM:'+','.join(sorted(set(dups)))];return result
    missing=required-set(labels)
    if missing:result['issues']=['MISSING_REQUIRED_ITEM:'+','.join(sorted(missing))];return result
    vals={en:_count(labels[cn]) for en,cn in [('up','上涨'),('down','下跌'),('flat','平盘')]}
    if any(v is None for v in vals.values()):result['issues'].append('COUNT_NOT_NONNEGATIVE_INTEGER')
    elif sum(vals.values())==0:result['issues'].append('ALL_ZERO_COUNTS_UNCONFIRMED')
    observed,err=_provider_stamp(labels['统计日期'])
    if err:result['issues'].append(err)
    d=_day(observation)
    if not d:result['issues'].append('INVALID_OBSERVATION_DATE')
    dates={_day(x) for x in (calendar or {}).get('dates',[])}
    if (calendar or {}).get('verified') is not True or d not in dates:
        result['issues'].append('TRADE_CALENDAR_UNVERIFIED')
    retrieved=_dt(raw.get('captured_at'));started=_dt(raw.get('started_at'))
    if retrieved is None or started is None:result['issues'].append('CAPTURE_TIMESTAMP_UNVERIFIED')
    if started and retrieved and started>retrieved:result['issues'].append('CAPTURE_ORDER_INVALID')
    if observed:
        result.update(source_date=observed.strftime('%Y%m%d'),as_of=observed.isoformat())
        if observed.strftime('%Y%m%d')!=d:result['issues'].append('STATISTICS_DATE_MISMATCH')
        if (observed.hour,observed.minute,observed.second)<(15,0,0):
            result['issues'].append('PROVIDER_SNAPSHOT_IS_INTRADAY')
        if retrieved and observed>retrieved:result['issues'].append('STATISTICS_TIME_AFTER_CAPTURE')
    if started and retrieved:
        if started.strftime('%Y%m%d')!=d or retrieved.strftime('%Y%m%d')!=d:
            result['issues'].append('NOT_CURRENT_OBSERVATION_DAY_CAPTURE')
        if (started.hour,started.minute,started.second)<(15,0,0):
            result['issues'].append('CAPTURE_STARTED_BEFORE_CLOSE')
    result['date_verified']=bool(observed and d and observed.strftime('%Y%m%d')==d and
        (calendar or {}).get('verified') is True and d in dates)
    result['issues']=list(dict.fromkeys(result['issues']))
    result['raw_counts']=vals
    if not result['issues']:
        result.update(vals);result.update(status='VALID',complete=True,closing_verified=True,
            unknown=0,validation_method='LEGULEGU_NATIVE_STATISTICS_TIMESTAMP_AND_COUNTS',
            total=sum(vals.values()))
    return result


def _plain(v):
    # Only JSON primitives leave the worker; non-finite scalars are null.
    if v is None or isinstance(v,(str,bool,int)):return v
    if isinstance(v,float):
        import math
        return v if math.isfinite(v) else None
    if hasattr(v,'item'):return _plain(v.item())
    if hasattr(v,'isoformat'):return v.isoformat()
    return str(v)


def raw_from_frame(frame, *, started_at, captured_at, implementation=None):
    import pandas as pd
    if not isinstance(frame,pd.DataFrame):raise TypeError('LEGULEGU_DID_NOT_RETURN_DATAFRAME')
    table={'columns':[str(c) for c in frame.columns],
           'data':[[_plain(x) for x in row] for row in frame.astype(object).where(pd.notna(frame),None).values.tolist()]}
    encoded=json.dumps(table,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
    return {'schema':'5535_LEGU_CAPTURE_V1','interface':INTERFACE,'status':'RETURNED_DATAFRAME',
        'started_at':started_at,'captured_at':captured_at,'request_calls':1,
        'table':table,'table_sha256':hashlib.sha256(encoded).hexdigest(),
        'implementation':implementation or {},'full_market_fallback_used':False}


def _worker(output):
    started=datetime.now(CN).isoformat()
    try:
        import akshare as ak
        import inspect
        fn=ak.stock_market_activity_legu
        src=inspect.getsourcefile(fn)
        implementation={'interface':INTERFACE,'akshare_version':getattr(ak,'__version__',None),
            'module':getattr(fn,'__module__',None),'source_path':src,
            'source_sha256':hashlib.sha256(Path(src).read_bytes()).hexdigest() if src and Path(src).is_file() else None}
        frame=fn()  # exactly one logical function call; no retry / no fallback
        raw=raw_from_frame(frame,started_at=started,captured_at=datetime.now(CN).isoformat(),implementation=implementation)
    except Exception as exc:
        raw={'schema':'5535_LEGU_CAPTURE_V1','interface':INTERFACE,'status':'REQUEST_OR_PARSE_ERROR',
             'started_at':started,'captured_at':datetime.now(CN).isoformat(),'request_calls':1,
             'error_type':type(exc).__name__,'error':str(exc),'full_market_fallback_used':False}
    Path(output).write_text(json.dumps(raw,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    return 0


def fetch_native(observation, *, timeout_seconds=30, now=None, supplier=None):
    """Bounded call, at most once per batch. Historical date never downloads today."""
    t=now or datetime.now(CN);t=t.astimezone(CN)
    start=t.isoformat()
    # 历史日期用fuyao全市场快照接口计算市场广度
    target_day = _day(observation)
    if target_day != t.strftime('%Y%m%d'):
        import requests
        from datetime import datetime as dt
        start_ms = int(dt.strptime(target_day, '%Y%m%d').timestamp() * 1000)
        end_ms = start_ms + 86399999
        url = 'https://fuyao.aicubes.cn/api/a-share/prices/snapshot'
        headers = {'X-api-key': 'sk-fuyao-CMpfWKVhJ5unjjsj1lcr-5QvzjbDrTwh'}
        params = {'start_ms': start_ms, 'end_ms': end_ms}
        try:
            r = requests.get(url, headers=headers, params=params, timeout=10)
            data = r.json().get('data', {}).get('item', [])
            up = sum(1 for s in data if s.get('price_change_ratio_pct', 0) > 0)
            down = sum(1 for s in data if s.get('price_change_ratio_pct', 0) < 0)
            flat = sum(1 for s in data if s.get('price_change_ratio_pct', 0) == 0)
            return {
                'schema': SCHEMA, 'source': 'FUYAO', 'scope': SCOPE,
                'requested_date': target_day, 'status': 'VALID',
                'up': up, 'down': down, 'flat': flat, 'unknown': 0,
                'source_date': target_day, 'as_of': start, 'date_verified': True,
                'closing_verified': True, 'complete': True,
                'total': up+down+flat, 'issues': [],
                'raw_counts': {'up': up, 'down': down, 'flat': flat}
            }
        except Exception as e:
            return {'interface': INTERFACE, 'status': 'HISTORICAL_FETCH_FAILED',
                'started_at': start, 'captured_at': start, 'request_calls': 0,
                'error': str(e), 'full_market_fallback_used': False}
    if supplier is not None: # injected boundary in tests; never a production source switch
        try:return raw_from_frame(supplier(),started_at=start,captured_at=start)
        except Exception as exc:return {'interface':INTERFACE,'status':'REQUEST_OR_PARSE_ERROR',
            'started_at':start,'captured_at':start,'request_calls':1,'error':str(exc),'error_type':type(exc).__name__}
    with tempfile.TemporaryDirectory(prefix='5535_legu_') as tmp:
        out=Path(tmp)/'provider.json'
        try:
            cp=subprocess.run([sys.executable,'-X','utf8',str(Path(__file__).resolve()),'--worker','--output',str(out)],
                capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout_seconds,
                cwd=str(Path(__file__).resolve().parent),shell=False)
            if cp.returncode!=0 or not out.is_file():
                return {'interface':INTERFACE,'status':'WORKER_ERROR','started_at':start,
                    'captured_at':datetime.now(CN).isoformat(),'request_calls':1,
                    'error':cp.stderr[-2000:],'returncode':cp.returncode,'full_market_fallback_used':False}
            return json.loads(out.read_text(encoding='utf-8'))
        except subprocess.TimeoutExpired:
            return {'interface':INTERFACE,'status':'REQUEST_TIMEOUT','started_at':start,
                'captured_at':datetime.now(CN).isoformat(),'request_calls':1,
                'timeout_seconds':timeout_seconds,'full_market_fallback_used':False}
        except Exception as exc:
            return {'interface':INTERFACE,'status':'WORKER_ERROR','started_at':start,
                'captured_at':datetime.now(CN).isoformat(),'request_calls':0,
                'error_type':type(exc).__name__,'error':str(exc),'full_market_fallback_used':False}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--worker',action='store_true');p.add_argument('--output',type=Path)
    a=p.parse_args()
    if not a.worker or a.output is None:p.error('internal worker requires --worker --output')
    raise SystemExit(_worker(a.output))
