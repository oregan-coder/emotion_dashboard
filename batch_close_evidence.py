"""Batch-level close evidence approved by the user for 5535.

The market spot feed may be certified as the observation-date closing batch only
when the verified exchange calendar, complete provider pagination and after-close
capture all agree.  This is a provenance rule, not a price replacement or a new
sample rule.

Existing Eastmoney event pools use their existing requested-date contract plus
transport completeness and an after-close capture.  No alternate provider is
introduced and raw values are never replaced.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
import re
from approved_policy import TradeCalendar, day

CN = timezone(timedelta(hours=8))
MARKET_METHOD = 'SINA_SPOT_BATCH_CLOSE_PROOF_V1'
POOL_METHOD = 'EASTMONEY_EVENT_POOL_BATCH_CLOSE_PROOF_V1'
SCHEMA = '5535_BATCH_CLOSE_EVIDENCE_V1'


def _stamp(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(CN)


def _valid_calendar(calendar_meta, observation):
    if not isinstance(calendar_meta, dict):
        return False
    cal = TradeCalendar(calendar_meta.get('dates', []), verified=calendar_meta.get('verified') is True,
                        source=calendar_meta.get('source', ''))
    return cal.verified and day(observation) in cal.dates


def _after_close(entries, observation, *, kinds):
    d = day(observation)
    times=[]
    for e in entries or []:
        if e.get('returned_to_fetcher') is not True or e.get('kind') not in kinds:
            continue
        t=_stamp(e.get('captured_at_utc'))
        if t is None:
            return False, [], 'CAPTURE_TIME_MISSING'
        times.append(t)
    if not times:
        return False, [], 'NO_CAPTURE_ENTRIES'
    # Historical backfill: capture date may be after the observation day.
    # Reject only if capture is before the observation day (data from a different day).
    if any(t.strftime('%Y%m%d') < d for t in times):
        return False, times, 'CAPTURE_BEFORE_OBSERVATION_DAY'
    # On the observation day, require after 15:00 close. Later days are backfill and OK.
    if any(t.strftime('%Y%m%d') == d and (t.hour, t.minute, t.second) < (15,0,0) for t in times):
        return False, times, 'CAPTURE_BEFORE_CLOSE'
    return True, times, None


def _prefilter_reconciles(frame, provider_total):
    attrs=getattr(frame,'attrs',{}) or {}
    ev=attrs.get('prefilter_evidence')
    if provider_total is None:
        return False, 'PROVIDER_TOTAL_MISSING'
    if len(frame) == provider_total:
        return True, None
    if not isinstance(ev, dict):
        return False, 'PREFILTER_EVIDENCE_MISSING'
    removed=ev.get('removed_codes')
    if not isinstance(removed, list) or any(not isinstance(c,str) or not re.fullmatch(r'\d{6}', c) for c in removed):
        return False, 'PREFILTER_REMOVED_CODES_INVALID'
    if ev.get('input_rows') != provider_total or ev.get('retained_rows') != len(frame):
        return False, 'PREFILTER_COUNTS_MISMATCH'
    if len(set(removed)) != len(removed) or len(frame) + len(removed) != provider_total:
        return False, 'PREFILTER_SET_SIZE_MISMATCH'
    return True, None


def prove_market_frame(frame, observation, calendar_meta):
    result={'schema':SCHEMA,'kind':'market','status':'DATA_PENDING','method':MARKET_METHOD,
            'source_date':None,'date_verified':False,'closing_verified':False,'complete':False,'issues':[]}
    if frame is None or not hasattr(frame,'attrs'):
        result['issues']=['MARKET_FRAME_MISSING'];return result
    if not _valid_calendar(calendar_meta, observation):
        result['issues']=['TRADE_CALENDAR_UNVERIFIED'];return result
    attrs=getattr(frame,'attrs',{}) or {}; transport=attrs.get('source_transport') or {}; summary=transport.get('summary') or {}
    issues=[]
    if transport.get('fetch_status') != 'RETURNED_DATAFRAME':issues.append('MARKET_FETCH_NOT_RETURNED_DATAFRAME')
    if summary.get('status') != 'COMPLETE_PROVIDER_COLLECTION_ONLY' or summary.get('provider_collection_complete') is not True:
        issues.append('PROVIDER_PAGINATION_INCOMPLETE')
    if summary.get('missing_pages') or summary.get('invalid_pages') or summary.get('duplicate_code_count') not in (0,None):
        issues.append('PROVIDER_PAGE_OR_CODE_CONFLICT')
    total=summary.get('provider_total')
    if type(total) is not int or total <= 0 or summary.get('unique_codes') != total or summary.get('returned_frame_rows') != total:
        issues.append('PROVIDER_TOTAL_OR_UNIQUENESS_MISMATCH')
    ok,why=_prefilter_reconciles(frame,total)
    if not ok:issues.append(why)
    time_ok,times,time_issue=_after_close(transport.get('entries'),observation,kinds={'SINA_COUNT','SINA_PAGE'})
    if not time_ok:issues.append(time_issue)
    if issues:
        result['issues']=sorted(set(issues));return result
    d=day(observation); available=max(times).isoformat()
    result.update(status='VALID',source_date=d,date_verified=True,closing_verified=True,complete=True,
                  available_at=available,provider_total=total,retained_rows=len(frame),
                  validation_scope='WHOLE_PROVIDER_SPOT_BATCH_BEFORE_APPROVED_LOCAL_FILTER',
                  approved_local_scope_complete=False,issues=[])
    return result


def _event_spec(key, observation, previous):
    if key=='limit_up':return '/getTopicZTPool', day(observation), day(observation), True
    if key=='limit_down':return '/getTopicDTPool', day(observation), day(observation), True
    if key=='open_board':return '/getTopicZBPool', day(observation), day(observation), True
    if key=='previous_limit_up':return '/getTopicZTPool', day(previous), day(previous), False
    if key=='previous_pool_performance':return '/getYesterdayZTPool', day(observation), day(observation), True
    raise KeyError(key)


def prove_event_frame(frame, key, observation, previous, calendar_meta):
    result={'schema':SCHEMA,'kind':key,'status':'DATA_PENDING','method':POOL_METHOD,
            'source_date':None,'date_verified':False,'closing_verified':False,'complete':False,'issues':[]}
    if frame is None or not hasattr(frame,'attrs'):
        result['issues']=['POOL_FRAME_MISSING'];return result
    if not _valid_calendar(calendar_meta, observation):
        result['issues']=['TRADE_CALENDAR_UNVERIFIED'];return result
    path,query_date,source_date,require_qdate=_event_spec(key,observation,previous)
    attrs=getattr(frame,'attrs',{}) or {}; transport=attrs.get('source_transport') or {}; summary=transport.get('summary') or {}
    entries=[e for e in transport.get('entries',[]) if e.get('returned_to_fetcher') is True and e.get('kind')=='EASTMONEY_POOL']
    issues=[]
    if transport.get('fetch_status')!='RETURNED_DATAFRAME':issues.append('POOL_FETCH_NOT_RETURNED_DATAFRAME')
    if summary.get('provider_collection_complete') is not True or summary.get('status') not in ('COMPLETE_PROVIDER_COLLECTION_ONLY','EMPTY_PROVIDER_COLLECTION_ONLY'):
        issues.append('POOL_TRANSPORT_INCOMPLETE')
    if len(entries)!=1:issues.append('POOL_CAPTURE_NOT_UNIQUE')
    e=entries[0] if len(entries)==1 else {}
    if e:
        if e.get('host')!='push2ex.eastmoney.com' or e.get('path')!=path or e.get('http_status')!=200 or e.get('rc')!=0:
            issues.append('POOL_RESPONSE_INVALID')
        if str(e.get('query',{}).get('date','')) != str(query_date):issues.append('POOL_REQUEST_DATE_MISMATCH')
        if e.get('upstream_data_is_null') is True:issues.append('POOL_DATA_NULL_NOT_EMPTY')
        total=e.get('provider_total'); rows=e.get('row_count'); unique=e.get('unique_code_count')
        if type(total) is not int or rows!=total or unique!=total or e.get('invalid_code_count',0)!=0:
            issues.append('POOL_TOTAL_OR_UNIQUENESS_MISMATCH')
        ok,why=_prefilter_reconciles(frame,total)
        if not ok:issues.append(why)
        if require_qdate and str(e.get('qdate_raw','')) != str(observation) and str(e.get('query',{}).get('date','')) != str(observation):issues.append('POOL_QDATE_MISMATCH')
    time_ok,times,time_issue=_after_close(entries,observation,kinds={'EASTMONEY_POOL'})
    if not time_ok:issues.append(time_issue)
    if issues:
        result['issues']=sorted(set(issues));return result
    d=source_date;available=max(times).isoformat()
    result.update(status='VALID',source_date=d,date_verified=True,closing_verified=True,complete=True,
                  available_at=available,provider_total=e.get('provider_total'),retained_rows=len(frame),issues=[],
                  validation_scope='EVENT_POOL_MEMBERSHIP_AS_REQUESTED_DATE_AFTER_CLOSE')
    return result


def _apply(frame, proof):
    if frame is None or not hasattr(frame,'attrs') or proof.get('status')!='VALID':return
    frame.attrs['source_date']=proof['source_date']
    frame.attrs['complete']=True
    frame.attrs['closing_verified']=True
    frame.attrs['quote_finality_verified']=True
    frame.attrs['validation_method']=proof['method']
    frame.attrs['validation_evidence']=deepcopy(proof)
    frame.attrs['available_at']=proof.get('available_at')
    d=proof.get('source_date')
    if d:
        frame.attrs['as_of']=d[:4]+'-'+d[4:6]+'-'+d[6:]+'T15:00:00+08:00'
    frame.attrs['source_contract']={'schema':SCHEMA,'method':proof['method'],'price_replacement':False,
        'request_date_not_used_alone':True,'batch_conditions_all_required':True}


def apply_batch_close_proofs(data, calendar_meta):
    proofs={}
    proofs['market']=prove_market_frame(getattr(data,'market',None),data.date,calendar_meta)
    _apply(getattr(data,'market',None),proofs['market'])
    for key in ('limit_up','limit_down','open_board','previous_limit_up','previous_pool_performance'):
        proof=prove_event_frame(getattr(data,key,None),key,data.date,data.previous_date,calendar_meta)
        proofs[key]=proof;_apply(getattr(data,key,None),proof)
    valid=sum(p.get('status')=='VALID' for p in proofs.values())
    return {'schema':SCHEMA,'status':'VALID' if valid==len(proofs) else 'PARTIAL' if valid else 'DATA_PENDING',
            'date':day(data.date),'previous_date':day(data.previous_date),'proofs':proofs,
            'price_replacement':False,'user_approved_market_batch_rule':True}


def upgrade_saved_bundle(bundle):
    """Rebuild canonical records from saved post-fetcher frames using this proof.

    Intended for deterministic historical repair/backfill. It never changes raw
    frame bytes/values and never invents identity beyond the bundle's own stored
    master-derived canonical records.
    """
    from approved_data_adapter import _restore_frame, receipt, normalize_frame
    from input_contracts import boolean
    from approved_policy import board_count
    import pandas as pd
    obj=deepcopy(bundle)
    specs=obj.get('frame_inputs') or {}
    required=('market','limit_up','limit_down','open_board','previous_limit_up','previous_pool_performance')
    if any(k not in specs for k in required):
        raise ValueError('SAVED_FRAME_SET_INCOMPLETE')
    frames={k:_restore_frame(specs[k]) for k in required}
    data=type('SavedFrames',(),{})()
    data.date=obj.get('date');data.previous_date=obj.get('previous_date')
    for k,v in frames.items():setattr(data,k,v)
    proof=apply_batch_close_proofs(data,obj.get('calendar') or {})
    # Persist only metadata additions in the saved frame specs; raw table values stay byte-identical logically.
    for k,f in frames.items():
        obj['frame_inputs'][k]['attrs']=deepcopy(dict(f.attrs))
    meta={k:receipt(frames[k],data.previous_date if k=='previous_limit_up' else data.date,k) for k in required}
    identities={}
    for r in list(obj.get('today_records',[]))+list(obj.get('previous_records',[])):
        c=r.get('code')
        if not c:continue
        identities[c]={'code':c,'market_board':r.get('market_board') or 'UNKNOWN',
                       'listing_date':r.get('listing_date'),'source':{'interface':'SAVED_CANONICAL_IDENTITY'},
                       'quote_date_proof':False}
    listings={c:r.get('listing_date') for c,r in identities.items()}
    today=normalize_frame(frames['market'],listing_dates=listings,master_identities=identities,source_meta=meta['market'])
    tm={r['code']:r for r in today if r.get('code')}
    for field,flag in [('limit_up','is_limit_up'),('limit_down','is_limit_down'),('open_board','touched_limit_up')]:
        rr=normalize_frame(frames[field],listing_dates=listings,master_identities=identities,source_meta=meta[field])
        if meta[field].get('date_verified') is not True:continue
        members={r['code'] for r in rr if r.get('code')}
        for c,row in tm.items():
            if c in members:row[flag]=True
            elif meta[field].get('complete') is True:row[flag]=False
        for row in rr:
            c=row.get('code')
            if not c:continue
            if c not in tm:tm[c]=row
            elif field=='limit_up':
                for key in ('board','seal_time','last_seal_time','seal_amount','turnover','open_count','amount','float_mv','industry'):
                    if row.get(key) is not None:tm[c][key]=row[key]
                if row.get('is_limit_up') is True:tm[c]['touched_limit_up']=True
    for row in tm.values():
        if row.get('is_limit_up') is True:
            row['touched_limit_up']=True;row['is_limit_down']=False
    perf=normalize_frame(frames['previous_pool_performance'],listing_dates=listings,master_identities=identities,source_meta=meta['previous_pool_performance'])
    for row in perf:
        if row.get('code') in tm and row.get('source_date')==day(data.date) and tm[row['code']].get('change_pct') is None:
            tm[row['code']]['change_pct']=row.get('change_pct')
    prior=normalize_frame(frames['previous_limit_up'],listing_dates=listings,master_identities=identities,source_meta=meta['previous_limit_up'])
    if meta['previous_limit_up'].get('date_verified') is True:
        for row in prior:row['is_limit_up']=True
    obj['today_records']=list(tm.values());obj['previous_records']=prior
    obj['source_meta']={'today':meta['market'],'previous':meta['previous_limit_up']}
    obj['acquisition_receipts']=meta
    obj['batch_close_evidence']=proof
    return obj
