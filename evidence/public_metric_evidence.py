"""User-authorised SAME provider verification for metric-specific event cohorts.

The union is dynamic (not hard-coded 98). It is NOT a full-market breadth feed.
Original frames/prices remain unchanged. One dated request is reused per symbol.
Only complete, captured provider EVENT pools can establish absence in that pool.
A transport-complete pool is not sufficient without dated price/identity matches.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import time
from evidence.candidate_quote_evidence import (rows, code, cents, numeric, day, stamp,
    parse_bars, pool_proof, request_bars, evaluate_candidate, METHOD, SCHEMA)
from core.approved_policy import TradeCalendar, scope_decision, cohort_metric, highest_board_2b
from core.input_contracts import board_count

SCOPE = 'PUBLIC_METRIC_EFFECTIVE_COHORTS'
PUBLIC_SCHEMA = '5535_PUBLIC_METRIC_PROOF_V1'
PATHS = {'limit_up':'/getTopicZTPool','limit_down':'/getTopicDTPool',
         'open_board':'/getTopicZBPool','previous_limit_up':'/getTopicZTPool',
         'previous_pool_performance':'/getYesterdayZTPool'}
CN = timezone(timedelta(hours=8))


def index(seq):
    out, conflicts, invalid = {}, set(), 0
    for r in seq:
        c=code(r)
        if not c: invalid += 1; continue
        if c in out and out[c] != r: conflicts.add(c)
        out[c]=r
    return out, sorted(conflicts), invalid


def enabled(policy):
    return (isinstance(policy,dict) and policy.get('enabled') is True
            and policy.get('scope') == SCOPE
            and policy.get('public_scope_approval_action') == 'AUTHORIZE_PUBLIC_METRIC_COHORTS'
            and stamp(policy.get('public_scope_approved_at')) is not None
            and policy.get('replace_original_prices') is False)


def pool_capture(frame, key, d, p):
    requested=p if key=='previous_limit_up' else d
    ent, issues=pool_proof(frame, PATHS[key], requested,
                          response_day=None if key=='previous_limit_up' else d)
    mp,conflicts,invalid=index(rows(frame))
    issues=list(issues)
    if conflicts or invalid: issues.append('FRAME_IDENTITY_CONFLICT_OR_INVALID')
    if ent:
        members=ent.get('codes',[])
        if (type(ent.get('provider_total')) is not int or
            ent['provider_total'] != ent.get('row_count') or
            len(members)!=len(set(members)) or len(members)!=ent.get('provider_total')):
            issues.append('EVENT_POOL_TOTAL_OR_UNIQUENESS_MISMATCH')
        attrs=getattr(frame,'attrs',{}) or {}
        pf=attrs.get('prefilter_evidence',{})
        removed=pf.get('removed_codes',[])
        removed=set(removed) if isinstance(removed,list) and all(isinstance(c,str) for c in removed) else set()
        if set(members) != set(mp)|removed or set(mp)&removed:
            issues.append('EVENT_POOL_PREFILTER_SET_UNEXPLAINED')
        # Removed rows have no payload. Only known outside-A-share board codes
        # are accepted as explained absences here; no guess that a missing row is ST.
        from core.approved_policy import exchange_board
        if any(exchange_board(c) != 'OUTSIDE' for c in removed):
            issues.append('REMOVED_MEMBER_SCOPE_REQUIRES_ORIGINAL_ROW')
        if ent.get('upstream_data_is_null') is True:
            issues.append('PROVIDER_DATA_NULL_NOT_EMPTY_MARKET')
        if not members:
            issues.append('EMPTY_POOL_HAS_NO_DATED_MEMBER_PROOF')
    return {'key':key,'status':'CAPTURED' if not issues else 'DATA_PENDING',
            'entry':ent,'issues':sorted(set(issues)), 'members':mp,
            'provider_event_pool_only':True, 'full_market_proven':False}


def check_member(c, row, key, capture, bar_receipt, d, p):
    expected=p if key=='previous_limit_up' else d
    bars, bad=parse_bars(bar_receipt,c)
    issues=list(bad)+list(capture['issues'])
    acquired=stamp(bar_receipt.get('captured_at'))
    if acquired is None or acquired.strftime('%Y%m%d') < d or (acquired.strftime('%Y%m%d')==d and acquired.hour < 15):
        issues.append('DATED_REFERENCE_ACQUIRED_BEFORE_CLOSE_OR_UNKNOWN')
    bar=bars.get(expected)
    if not bar:issues.append('EXPECTED_DAILY_DATE_MISSING')
    elif cents(row.get('最新价')) is None or cents(row.get('最新价'))!=cents(bar.get('close')):
        issues.append('ORIGINAL_AND_DAILY_CLOSE_MISMATCH')
    if bar:
        volume=numeric(bar.get('volume_lots'))
        if volume is None or volume<=0:
            issues.append('NO_CURRENT_TRADES_OR_SUSPENSION_UNRESOLVED')
    if bar and key=='open_board':
        lim=cents(row.get('涨停价')); high=cents(bar.get('high')); close=cents(bar.get('close'))
        if lim is None or high!=lim or close is None or close>=lim:
            issues.append('OPEN_BOARD_NOT_CONFIRMED_BY_LIMIT_PRICE_AND_DAILY_HIGH')
    when=stamp((capture.get('entry') or {}).get('captured_at_utc'))
    return {'code':c,'status':'VALID' if not issues else 'DATA_PENDING','issues':sorted(set(issues)),
        'source_date':expected if not issues else None,'date_verified':not issues,'closing_verified':not issues,
        'available_at':max(acquired,when).isoformat() if acquired and when else None,
        'daily_open':bar.get('open') if bar else None, 'daily_close':bar.get('close') if bar else None,
        'daily_high':bar.get('high') if bar else None,
        'daily_response_sha256':bar_receipt.get('response_sha256'),
        'pool_response_sha256':(capture.get('entry') or {}).get('response_sha256'),
        'price_replacement':False}


def _batch_close_ready(data):
    market=getattr(data,'market',None)
    if getattr(market,'attrs',{}).get('validation_method')!='SINA_SPOT_BATCH_CLOSE_PROOF_V1':
        return False
    for key in PATHS:
        if getattr(getattr(data,key,None),'attrs',{}).get('validation_method')!='EASTMONEY_EVENT_POOL_BATCH_CLOSE_PROOF_V1':
            return False
    return True


def _collect_public_batch(data, identities, cal_meta, *, policy, fetch=None, budget_seconds=90):
    """Public metrics are delegated to batch-certified canonical frames.

    Only current two-board candidates receive extra dated OHLC requests.  This
    preserves D-factor/two-open-limit evidence without serially re-requesting the
    whole public cohort.
    """
    d,p=day(data.date),day(data.previous_date)
    cal=TradeCalendar(cal_meta.get('dates',[]),verified=cal_meta.get('verified') is True)
    frames={k:getattr(data,k,None) for k in PATHS}
    current=[r for r in rows(data.limit_up) if type(r.get('连板数')) is not bool and r.get('连板数')==2]
    cmap,_conf,_invalid=index(current)
    pmap=index(rows(data.previous_limit_up))[0]
    perf=index(rows(data.previous_pool_performance))[0]
    out={'schema':SCHEMA,'method':METHOD,'policy':deepcopy(policy),'status':'COMPLETE_WITH_PENDING',
         'records':{},'requests':{},'price_replacement':False,'full_market_proven':False,
         'public_metrics':{'schema':PUBLIC_SCHEMA,'scope':SCOPE,'date':d,'previous_date':p,
             'mode':'BATCH_CLOSE_DELEGATED','requested_codes':sorted(cmap),'request_order':sorted(cmap),
             'pool_checks':{},'member_checks':{},'full_market_breadth_proven':False,
             'price_replacement':False,'method':'BATCH_CLOSE_PLUS_CANDIDATE_DATED_OHLC'}}
    if not enabled(policy): out['status']='PUBLIC_SCOPE_NOT_APPROVED'; return out
    if not cal.verified or cal.previous(d)!=p: out['status']='CALENDAR_RELATION_UNPROVEN'; return out
    call=fetch or request_bars;deadline=time.monotonic()+min(int(budget_seconds or 90),120)
    for c,r in sorted(cmap.items()):
        ident=identities.get(c,{})
        if time.monotonic()>=deadline:receipt={'status':'CHECK_TIME_BUDGET_EXHAUSTED'}
        elif ident.get('identity_conflict') or ident.get('listing_date_conflict') or ident.get('market_board') not in {'SSE_MAIN_A','SZSE_MAIN_A','CHINEXT_A','STAR_A'}:
            receipt={'status':'MASTER_IDENTITY_UNPROVEN'}
        else:
            try: receipt=call(c,ident['market_board'],p,d)
            except Exception as exc: receipt={'status':'REQUEST_ERROR','error_type':type(exc).__name__,'error':str(exc)}
        out['requests'][c]=receipt
        out['records'][c]=evaluate_candidate(c,r,pmap.get(c),perf.get(c),frames,receipt,d,p,cal)
    pub=out['public_metrics']
    for key in PATHS:
        attrs=getattr(getattr(data,key,None),'attrs',{}) or {}
        proof=attrs.get('validation_evidence') or {}
        pub['pool_checks'][key]={'status':'VALID' if proof.get('status')=='VALID' else 'DATA_PENDING',
            'complete':proof.get('complete') is True,'member_codes':sorted(index(rows(getattr(data,key,None)))[0]),
            'batch_proof':deepcopy(proof)}
    pub['requested_count']=len(cmap)
    pub['request_status_counts']={st:sum(r.get('status')==st for r in out['requests'].values())
                                  for st in sorted({r.get('status','UNKNOWN') for r in out['requests'].values()})}
    out['validated_candidates']=sum(x.get('status')=='VALID' for x in out['records'].values())
    return out


def collect_public(data, identities, cal_meta, *, policy, fetch=None, budget_seconds=480):
    from collection.market_breadth_legu import MODE
    if getattr(data, 'collection_mode', None) == MODE:
        # Event-pool receipts are evaluated independently downstream. Only the
        # already-authorised current two-board candidates need extra OHLC here.
        return _collect_public_batch(data, identities, cal_meta, policy=policy, fetch=fetch,
                                     budget_seconds=min(budget_seconds,120))
    if _batch_close_ready(data):
        return _collect_public_batch(data,identities,cal_meta,policy=policy,fetch=fetch,
                                     budget_seconds=min(budget_seconds,120))
    return _collect_public_per_member(data,identities,cal_meta,policy=policy,fetch=fetch,
                                      budget_seconds=budget_seconds)


def _collect_public_per_member(data, identities, cal_meta, *, policy, fetch=None, budget_seconds=480):
    """Called by existing candidate entry only when public scope has been approved."""
    d,p=day(data.date),day(data.previous_date)
    cal=TradeCalendar(cal_meta.get('dates',[]),verified=cal_meta.get('verified') is True)
    frames={k:getattr(data,k,None) for k in PATHS}
    caps={k:pool_capture(f,k,d,p) for k,f in frames.items()}
    # Performance should not silently add members that were not yesterday's pool.
    codes=set().union(*(set(caps[k]['members']) for k in ('limit_up','limit_down','open_board','previous_limit_up')))
    out={'schema':SCHEMA,'method':METHOD,'policy':deepcopy(policy),'status':'COMPLETE_WITH_PENDING',
         'records':{},'requests':{},'price_replacement':False,'full_market_proven':False,
         'public_metrics':{'schema':PUBLIC_SCHEMA,'scope':SCOPE,'date':d,'previous_date':p,
             'requested_codes':sorted(codes),'pool_checks':{},'member_checks':{},
             'full_market_breadth_proven':False,'price_replacement':False,'method':METHOD}}
    pub=out['public_metrics']
    if not enabled(policy):
        out.update(status='PUBLIC_SCOPE_NOT_APPROVED');return out
    if not cal.verified or cal.previous(d)!=p:
        out.update(status='CALENDAR_RELATION_UNPROVEN');return out
    call=fetch or request_bars
    deadline=time.monotonic()+budget_seconds
    stop_reason=None
    # Preserve existing candidate checks under the wider time budget: current
    # two-board stocks first, then the prior cohort, then the remaining pools.
    candidates=sorted(c for c,r in caps['limit_up']['members'].items()
                      if type(r.get('连板数')) is not bool and r.get('连板数')==2)
    prior=sorted(set(caps['previous_limit_up']['members'])-set(candidates))
    request_order=candidates+prior+sorted(codes-set(candidates)-set(prior))
    pub['request_order']=request_order
    for c in request_order:
        ident=identities.get(c,{})
        if stop_reason:
            receipt={'status':stop_reason}
        elif time.monotonic()>=deadline:
            receipt={'status':'CHECK_TIME_BUDGET_EXHAUSTED'}
        elif ident.get('identity_conflict') or ident.get('listing_date_conflict') or ident.get('market_board') not in {'SSE_MAIN_A','SZSE_MAIN_A','CHINEXT_A','STAR_A'}:
            receipt={'status':'MASTER_IDENTITY_UNPROVEN'}
        else:
            try:receipt=call(c,ident['market_board'],p,d)
            except Exception as exc:receipt={'status':'REQUEST_ERROR','error_type':type(exc).__name__}
            if receipt.get('http_status') in (401,403,407,429) or receipt.get('retry_after_present'):
                stop_reason='PROVIDER_ACCESS_OR_RETRY_AFTER_STOPPED'
            # Serial, bounded requests; never parallel overload or alternate endpoint.
        out['requests'][c]=receipt
    for key,cap in caps.items():
        mm={c:check_member(c,r,key,cap,out['requests'].get(c,{}),d,p) for c,r in cap['members'].items()}
        pub['member_checks'][key]=mm
        pub['pool_checks'][key]={k:v for k,v in cap.items() if k not in ('members','entry')}
        pub['pool_checks'][key].update(member_codes=sorted(cap['members']),
            transport_entry=cap['entry'],dated_member_count=sum(m['status']=='VALID' for m in mm.values()),
            complete=bool(mm) and not cap['issues'] and all(m['status']=='VALID' for m in mm.values()))
    # Yesterday membership is independently crosschecked with today's dedicated yesterday pool.
    pm=caps['previous_limit_up']['members'];perf=caps['previous_pool_performance']['members']
    membership_same=set(pm)==set(perf)
    for c,m in pub['member_checks']['previous_limit_up'].items():
        extra=[]
        if not membership_same:extra.append('PREVIOUS_AND_PERFORMANCE_MEMBERSHIP_DIFFER')
        if c not in perf or pm[c].get('连板数')!=perf.get(c,{}).get('昨日连板数'):
            extra.append('PREVIOUS_BOARD_CROSSCHECK_MISMATCH')
        # The previous daily bar verifies yesterday. Today's performance price
        # is a separate proof and may fail without rewriting yesterday's value.
        if caps['previous_pool_performance']['issues']:extra+=caps['previous_pool_performance']['issues']
        if extra:m.update(status='DATA_PENDING',date_verified=False,closing_verified=False,source_date=None,issues=sorted(set(m['issues']+extra)))
    for key in PATHS:
        ck=pub['pool_checks'][key];mm=pub['member_checks'][key]
        ck['complete']=bool(mm) and not ck['issues'] and all(m['status']=='VALID' for m in mm.values())
        ck['status']='VALID' if ck['complete'] else 'DATA_PENDING'
    pub['prior_membership_same']=membership_same
    # Preserve the original per-candidate validation contract and reuse each fetched response.
    for c,r in caps['limit_up']['members'].items():
        if type(r.get('连板数')) is bool or r.get('连板数')!=2:continue
        out['records'][c]=evaluate_candidate(c,r,pm.get(c),perf.get(c),frames,
            out['requests'].get(c,{}),d,p,cal)
    out['validated_candidates']=sum(m.get('status')=='VALID' for m in out['records'].values())
    times=[stamp(m.get('available_at')) for mm in pub['member_checks'].values() for m in mm.values()]
    times=[t for t in times if t]
    pub['available_at']=max(times).isoformat() if times else None
    pub['requested_count']=len(codes)
    pub['request_status_counts']={s:sum(r.get('status')==s for r in out['requests'].values()) for s in sorted({r.get('status','UNKNOWN') for r in out['requests'].values()})}
    return out


def apply_to_bundle(bundle):
    """Add derived dates/states ONLY after exact original-value matches. Never copy prices."""
    obj=bundle.get('candidate_quote_evidence',{})
    if not enabled(obj.get('policy')):return
    pub=obj.get('public_metrics',{})
    if pub.get('schema')!=PUBLIC_SCHEMA or pub.get('date')!=bundle.get('date') or pub.get('previous_date')!=bundle.get('previous_date'):return
    if pub.get('mode')=='BATCH_CLOSE_DELEGATED':
        # Canonical rows already received their date/finality and pool states
        # from the approved batch proof before normalization.
        return
    tm={r.get('code'):r for r in bundle.get('today_records',[])}
    pm={r.get('code'):r for r in bundle.get('previous_records',[])}
    raw_frames={}
    for name,spec in bundle.get('frame_inputs',{}).items():
        cols=spec.get('columns',[]); raw_frames[name]=index([dict(zip(cols,r)) for r in spec.get('data',[])])[0]
    for key,checks in pub.get('member_checks',{}).items():
        target=pm if key=='previous_limit_up' else tm
        for c,m in checks.items():
            row=target.get(c)
            if row is None or m.get('status')!='VALID':continue
            if cents(row.get('close'))!=cents(m.get('daily_close')):
                m.update(status='DATA_PENDING',issues=list(m.get('issues',[]))+['CANONICAL_ORIGINAL_CLOSE_CONFLICT']);continue
            if key!='previous_limit_up' and row.get('open') is not None and cents(row['open'])!=cents(m.get('daily_open')):
                m.update(status='DATA_PENDING',issues=list(m.get('issues',[]))+['CANONICAL_ORIGINAL_OPEN_CONFLICT']);continue
            row['source_date']=m['source_date'];row['date_verified']=True;row['closing_verified']=True
            if key=='limit_up':
                from core.input_contracts import board_count, number, integer
                source=raw_frames.get(key,{}).get(c,{})
                mapping={'board':'连板数','seal_time':'首次封板时间','last_seal_time':'最后封板时间',
                    'seal_amount':'封板资金','turnover':'换手率','open_count':'炸板次数',
                    'amount':'成交额','float_mv':'流通市值','industry':'所属行业'}
                for field,column in mapping.items():
                    value=source.get(column)
                    if value is None or row.get(field) is not None:continue
                    if field=='board':value=board_count(value)
                    elif field=='open_count':value=integer(value,minimum=0)
                    elif field in ('seal_amount','turnover','amount','float_mv'):value=number(value)
                    row[field]=value
                    row.setdefault('public_field_sources',{})[field]={'frame':key,'column':column,'code':c}
            row['as_of']=m['source_date'][:4]+'-'+m['source_date'][4:6]+'-'+m['source_date'][6:]+'T15:00:00+08:00'
            row['public_metric_evidence']={'method':METHOD,'available_at':m.get('available_at'),
                'proof_pointer':'/candidate_quote_evidence/public_metrics/member_checks/'+key+'/'+c}
            if key in ('limit_up','previous_limit_up'):
                row['is_limit_up']=True;row['open_at_limit']=cents(m['daily_open'])==cents(m['daily_close'])
                if key=='limit_up':row['touched_limit_up']=True;row['is_limit_down']=False
            elif key=='limit_down':row['is_limit_down']=True;row['is_limit_up']=False
            elif key=='open_board':row['touched_limit_up']=True;row['is_limit_up']=False;row['is_limit_down']=False
    # Fail changed/conflicting canonical records closed in the relevant pool only.
    for key,ck in pub.get('pool_checks',{}).items():
        ck['complete']=ck.get('complete') is True and all(m.get('status')=='VALID' for m in pub['member_checks'][key].values())
        ck['status']='VALID' if ck['complete'] else 'DATA_PENDING'
    up_ok=pub.get('pool_checks',{}).get('limit_up',{}).get('complete') is True
    up=set(pub.get('pool_checks',{}).get('limit_up',{}).get('member_codes',[]))
    if up_ok:
        for c,m in pub.get('member_checks',{}).get('previous_pool_performance',{}).items():
            row=tm.get(c)
            if row and m.get('status')=='VALID' and row.get('source_date')==bundle['date']:
                row['is_limit_up']=c in up
                if c not in up:row['board']=0  # Derived non-limit-up state, not an invented price.


def metric_overrides(bundle, context):
    """Return independently proven metric values without certifying broad-market rows."""
    ce=bundle.get('candidate_quote_evidence',{});pub=ce.get('public_metrics',{})
    if not enabled(ce.get('policy')) or pub.get('schema')!=PUBLIC_SCHEMA:return context
    d,p=bundle['date'],bundle['previous_date']
    if pub.get('date')!=d or pub.get('previous_date')!=p:return context
    if pub.get('mode')=='BATCH_CLOSE_DELEGATED':
        result=deepcopy(context)
        result['public_verification_summary']={'scope':SCOPE,'mode':'BATCH_CLOSE_DELEGATED',
            'requested_count':pub.get('requested_count',0),'request_status_counts':pub.get('request_status_counts',{}),
            'pool_checks':deepcopy(pub.get('pool_checks',{})),'full_market_breadth_proven':False}
        return result
    cal=TradeCalendar(bundle['calendar'].get('dates',[]),verified=bundle['calendar'].get('verified') is True)
    tm={r.get('code'):r for r in bundle.get('today_records',[])};pm={r.get('code'):r for r in bundle.get('previous_records',[])}
    result=deepcopy(context); evidence={}
    def pool(key,which):
        ck=pub.get('pool_checks',{}).get(key,{})
        wanted=ck.get('member_codes',[]);date=p if which is pm else d
        decisions=[scope_decision(which.get(c,{'code':c}),date,cal) for c in wanted]
        ok=(ck.get('complete') is True and all(x['status'] in ('ELIGIBLE','EXCLUDED') for x in decisions))
        eligible=[x['code'] for x in decisions if x['status']=='ELIGIBLE']
        return ok,eligible,decisions
    pools={k:pool(k,pm if k=='previous_limit_up' else tm) for k in PATHS}
    def proof(keys,valid):
        return {'status':'VALID' if valid else 'DATA_PENDING','date_verified':valid,'closing_verified':valid,
            'source_date':d,'source_dates':[d,p] if 'previous_limit_up' in keys else [d],
            'complete':valid,'available_at':pub.get('available_at'),'scope':SCOPE,
            'source':'VERIFIED_EXISTING_EASTMONEY_EVENT_POOLS','pool_dependencies':keys,
            'full_market_breadth_proven':False,'unresolved_pools':[k for k in keys if not pools[k][0]]}
    uok,up,_=pools['limit_up'];dok,dn,_=pools['limit_down'];zok,zb,_=pools['open_board']
    overlap=(set(up)&set(dn))|(set(up)&set(zb))|(set(dn)&set(zb))
    if overlap:uok=dok=zok=False
    for key,ok in [('limit_up',uok),('limit_down',dok)]:evidence[key]=proof([key],ok)
    counts=deepcopy(result['counts'])
    if uok:counts['up']=len(up)
    if dok:counts['down']=len(dn)
    counts.update(status='VALID' if uok and dok else 'PARTIAL' if uok or dok else 'DATA_PENDING',
        up_status='VALID' if uok else 'DATA_PENDING',down_status='VALID' if dok else 'DATA_PENDING',
        source_scope=SCOPE,full_market_breadth_proven=False)
    result['counts']=counts
    # Do not replace context.scope/breadth or source_meta.today with the 98-symbol union.
    if uok and zok:
        union=sorted(set(up)|set(zb))
        result['failed_limitup_rate']={'name':'failed_limitup_rate','value':len(zb)/len(union)*100 if union else None,
            'status':'VALID' if union else 'EMPTY_EFFECTIVE','unit':'%','numerator':len(zb),'denominator':len(union),
            'numerator_codes':sorted(zb),'denominator_codes':union,'unknown_codes':[],'source_scope':SCOPE}
    evidence['failed_limitup_rate']=proof(['limit_up','open_board'],uok and zok and bool(up or zb))
    if uok:
        meta=proof(['limit_up'],True);meta.update(scope='APPROVED_LOCAL',as_of=d[:4]+'-'+d[4:6]+'-'+d[6:]+'T15:00:00+08:00')
        result['highest_board']=highest_board_2b([tm[c] for c in up],meta,d,cal)
        from collections import Counter
        result['known_ladder']=dict(Counter(tm[c].get('board') for c in up if tm[c].get('board') is not None))
    evidence['highest_board']=proof(['limit_up'],uok and result['highest_board'].get('status')=='VALID')
    pok,pc,_=pools['previous_limit_up'];fok,fc,_=pools['previous_pool_performance']
    # A complete historical cohort can use its independently verified current
    # members, removing failed/missing current quotes under the approved policy.
    prior_meta={'status':'VALID' if pok else 'DATA_PENDING','source_date':p if pok else None,'date_verified':pok,'complete':pok,'closing_verified':pok}
    # Date presence of valid daily matches establishes per-cohort quote coverage;
    # no blanket claim that all current rows or all provider records are known.
    verified_current=[tm[c] for c in pc if c in tm and tm[c].get('source_date')==d and tm[c].get('closing_verified') is True]
    any_current=bool(verified_current)
    today_meta={'status':'PARTIAL' if any_current else 'DATA_PENDING','date_verified':any_current,'source_date':d if any_current else None,'complete':False,'closing_verified':any_current}
    common=dict(prior_records=list(pm.values()),today_records=verified_current,prior_date=p,observation=d,calendar=cal,today_meta=today_meta,prior_meta=prior_meta)
    if pok:
        continuation=cohort_metric(**common)
        high=cohort_metric(**common,kind='failure',board_min=4)
        promos={str(k):cohort_metric(**common,kind='promotion',board_exact=k) for k in range(1,max(5,max((board_count(r.get('board')) or 0 for r in prior),default=0))+1)}
        mean=cohort_metric(**common,kind='mean_change')
        result.update(continuation=continuation,high_board_fail_rate=high,promotions=promos)
        from core.approved_policy import select_yesterday_performance
        result['yesterday_performance']=select_yesterday_performance(bundle.get('primary_883900'),mean,d)
    for name,val in [('continuation',result['continuation']),('high_board_fail_rate',result['high_board_fail_rate']),('yesterday_performance',result['yesterday_performance'])]:
        evidence[name]=proof(['previous_limit_up','previous_pool_performance']+([] if name=='yesterday_performance' else ['limit_up']),val.get('status')=='VALID' and pok)
    for k,m in result['promotions'].items():evidence['rate'+k+str(int(k)+1)]=proof(['previous_limit_up','limit_up','previous_pool_performance'],m.get('status')=='VALID' and pok)
    result['metric_evidence']=evidence
    result['public_verification_summary']={k:deepcopy(pub.get(k)) for k in ('scope','requested_count','request_status_counts','available_at','pool_checks','full_market_breadth_proven')}
    return result
