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
    # Historical Fuyao snapshots are already a complete, date-scoped aggregate
    # produced in fetch_native.  They do not have LEGULEGU's item/value table,
    # so validate their independent aggregate contract before legacy parsing.
    if isinstance(raw, dict) and raw.get('source') == 'FUYAO':
        result = pending('NOT_PARSED', requested_date=observation, raw=raw)
        d = _day(observation)
        counts = {key: _count(raw.get(key)) for key in ('up', 'down', 'flat', 'unknown', 'total')}
        issues = []
        if raw.get('status') != 'VALID':
            issues.append(str(raw.get('status', 'FUYAO_STATUS_MISSING')))
        if raw.get('source_date') != d or raw.get('date_verified') is not True:
            issues.append('FUYAO_DATE_MISMATCH')
        if raw.get('closing_verified') is not True or raw.get('complete') is not True:
            issues.append('FUYAO_FINALITY_OR_COMPLETENESS_MISSING')
        if any(value is None for value in counts.values()):
            issues.append('FUYAO_COUNT_INVALID')
        elif counts['up'] + counts['down'] + counts['flat'] + counts['unknown'] != counts['total']:
            issues.append('FUYAO_COUNT_TOTAL_MISMATCH')
        dates = {_day(item) for item in (calendar or {}).get('dates', [])}
        if (calendar or {}).get('verified') is not True or d not in dates:
            issues.append('TRADE_CALENDAR_UNVERIFIED')
        if issues:
            result['issues'] = issues
            return result
        return {
            **result,
            **counts,
            'source': 'FUYAO', 'requested_date': d, 'source_date': d,
            'status': 'VALID', 'date_verified': True, 'closing_verified': True,
            'complete': True, 'as_of': raw.get('as_of'),
            'available_at': raw.get('as_of'), 'issues': [],
            'raw_counts': {key: counts[key] for key in ('up', 'down', 'flat', 'unknown')},
            'validation_method': 'FUYAO_SNAPSHOT_CODE0_COMPLETE_TOTAL_DATE_WINDOW',
        }
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


def _snapshot_anchor_check(items, frames):
    from core.input_contracts import find_column, normalize_code
    lookup = {normalize_code(item.get('ticker') or item.get('thscode')): item for item in items}
    anchors = []
    for frame in frames or ():
        if frame is None or not hasattr(frame, 'columns'):
            continue
        code = find_column(frame, ['代码', '股票代码', '证券代码', 'code'])
        price = find_column(frame, ['最新价', '收盘', '收盘价', 'close'])
        change = find_column(frame, ['涨跌幅', '涨幅', 'change_pct'])
        if not code or not price or not change:
            continue
        for _, row in frame.iterrows():
            expected_price, expected_change = row.get(price), row.get(change)
            if expected_price is None or expected_change is None:
                continue
            anchors.append((normalize_code(row.get(code)), expected_price, expected_change))
    if not anchors:
        return False, {'anchor_rows': 0, 'missing': [], 'price_mismatch': [], 'change_mismatch': []}
    missing, price_mismatch, change_mismatch = [], [], []
    for code, price, change in anchors:
        item = lookup.get(code)
        if not item:
            missing.append(code); continue
        try:
            if abs(float(price) - float(item.get('last_price'))) > 0.000001:
                price_mismatch.append(code)
            if abs(float(change) - float(item.get('price_change_ratio_pct'))) > 0.001:
                change_mismatch.append(code)
        except (TypeError, ValueError):
            price_mismatch.append(code)
    evidence = {'anchor_rows': len(anchors), 'missing': sorted(set(missing)),
        'price_mismatch': sorted(set(price_mismatch)), 'change_mismatch': sorted(set(change_mismatch))}
    return not any((missing, price_mismatch, change_mismatch)), evidence


def fetch_native(observation, *, timeout_seconds=30, now=None, supplier=None, anchor_frames=None):
    """Bounded call, at most once per batch. Historical date never downloads today."""
    t=now or datetime.now(CN);t=t.astimezone(CN)
    start=t.isoformat()
    # The Fuyao snapshot is current-only.  It may represent the latest close on
    # a weekend/holiday, but only after calendar and event-pool anchor checks.
    target_day = _day(observation)
    if target_day != t.strftime('%Y%m%d'):
        try:
            from collection.fuyao_provider import snapshot_rows, trading_days
            data, receipt = snapshot_rows(timeout=timeout_seconds)
            days = trading_days(timeout=timeout_seconds)
            latest = max((day for day in days if day <= receipt.get('source_date', '')), default=None)
            if target_day != latest:
                raise RuntimeError('FUYAO_SNAPSHOT_IS_CURRENT_ONLY_NOT_HISTORICAL')
            anchors_ok, anchors = _snapshot_anchor_check(data, anchor_frames)
            if not anchors_ok:
                raise RuntimeError('FUYAO_SNAPSHOT_EVENT_POOL_ANCHOR_MISMATCH')
            values = [s.get('price_change_ratio_pct') for s in data]
            numeric = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
            up = sum(1 for v in numeric if v > 0)
            down = sum(1 for v in numeric if v < 0)
            flat = sum(1 for v in numeric if v == 0)
            unknown = len(values) - len(numeric)
            return {
                'schema': SCHEMA, 'source': 'FUYAO', 'scope': SCOPE,
                'requested_date': target_day, 'status': 'VALID',
                'up': up, 'down': down, 'flat': flat, 'unknown': unknown,
                'source_date': target_day, 'as_of': start, 'date_verified': True,
                'closing_verified': True, 'complete': True,
                'total': len(values), 'issues': [],
                'raw_counts': {'up': up, 'down': down, 'flat': flat, 'unknown': unknown},
                'validation_evidence': {**receipt, 'calendar_latest_trading_day': latest,
                    'event_pool_anchor_check': anchors},
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
