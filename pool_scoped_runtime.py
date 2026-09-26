"""Pool-scoped price records + independent native aggregate breadth.

The sparse union is not an A-share universe. This module never feeds its median
or advance/decline counts to a whole-market statistic. Original rows and prices
remain in frame_inputs, with conflicts explicitly recorded rather than resolved.
"""
from __future__ import annotations
from copy import deepcopy
from collections import Counter
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from core.approved_policy import (TradeCalendar, day, filter_scope, scope_decision,
    cohort_metric, highest_board_2b, select_yesterday_performance, source_usable)
from core.input_contracts import number, boolean, board_count
from collection.market_breadth_legu import MODE, parse_native, SCOPE, SOURCE

KEYS=('limit_up','limit_down','open_board','previous_limit_up','previous_pool_performance')

# The event pools are NOT three disjoint outcomes.  open_board means
# touched upper limit earlier and is not sealed at the upper limit now.
# A stock may therefore belong to BOTH open_board AND limit_down.
# Current upper-limit membership conflicts with either current lower-limit
# membership or the *currently unsealed* open_board set.  Price/date conflicts
# remain independently blocking; mere permitted overlap never overrides them.
EVENT_RELATION_VERSION = '5535_EVENT_POOL_RELATION_V2'


def event_pool_relation(sets):
    up = set(sets.get('limit_up', ()))
    down = set(sets.get('limit_down', ()))
    failed = set(sets.get('open_board', ()))
    upper_lower = up & down
    upper_unsealed = up & failed
    lower_after_upper_touch = down & failed
    conflicts = upper_lower | upper_unsealed
    return {
        'schema': EVENT_RELATION_VERSION,
        'all_overlap_codes': sorted(upper_lower | upper_unsealed | lower_after_upper_touch),
        'conflicting_codes': sorted(conflicts),
        'compatible_overlap_codes': sorted(lower_after_upper_touch - conflicts),
        'pairs': {
            'limit_up_and_limit_down': {
                'codes': sorted(upper_lower), 'relationship': 'INCOMPATIBLE_CURRENT_STATES'},
            'limit_up_and_open_board': {
                'codes': sorted(upper_unsealed), 'relationship': 'INCOMPATIBLE_SEALED_AND_UNSEALED'},
            'limit_down_and_open_board': {
                'codes': sorted(lower_after_upper_touch),
                'relationship': 'COMPATIBLE_TOUCHED_UPPER_AND_CURRENTLY_LOWER'},
        },
        'price_conflicts_ignored': False,
        'date_checks_relaxed': False,
        'score_formula_changed': False,
    }


def final(meta,d):
    return source_usable(meta,d) and meta.get('closing_verified') is True


def complete(meta,d):
    return final(meta,d) and meta.get('complete') is True


def _fields(row,frame):
    return {k:{'frame':frame,'code':row.get('code'),'source_date':row.get('source_date')}
            for k,v in row.items() if v is not None and k not in ('market_board_evidence',)}


def build_bundle(data,cal_meta,identities,master_captures,meta,batch_evidence,
                 diagnostics,*,candidate_supplier=None,validation_policy=None,primary_supplier=None):
    from core.approved_data_adapter import normalize_frame,capture_frame_inputs,fetch_ths_883900
    from evidence.candidate_quote_evidence import collect_candidates,cents
    d,p=day(data.date),day(data.previous_date)
    listings={c:r.get('listing_date') for c,r in identities.items()}
    frames={k:getattr(data,k,None) for k in KEYS}
    rr={k:normalize_frame(f,listing_dates=listings,master_identities=identities,source_meta=meta[k])
        for k,f in frames.items()}
    tm={};conflicts=[]
    # Pool precedence selects a display value only. Conflicting values are
    # preserved in raw inputs and BLOCK the record, never silently replaced.
    for key in ('limit_up','limit_down','open_board','previous_pool_performance'):
        for row in rr[key]:
            c=row.get('code')
            if not c:continue
            row=deepcopy(row)
            if key=='previous_pool_performance':row['board']=None # yesterday's board is not today's
            row['pool_member_sources']=[key];row['field_sources']=_fields(row,key)
            if final(meta[key],d) and row.get('source_date')==d:
                row['date_verified']=True;row['closing_verified']=True
                row['as_of']=meta[key].get('as_of')
            if c not in tm:tm[c]=row;continue
            current=tm[c];current['pool_member_sources'].append(key)
            for field in ('close','open'):
                left,right=current.get(field),row.get(field)
                if left is not None and right is not None and cents(left)!=cents(right):
                    conflicts.append({'code':c,'field':field,'sources':current['pool_member_sources'][:],
                        'values':[left,right]})
                    current['record_conflict']=True
            for field,v in row.items():
                if field in ('board','pool_member_sources','field_sources'):continue
                if v is not None and current.get(field) is None:
                    current[field]=v;current.setdefault('field_sources',{})[field]=row['field_sources'].get(field)
    sets={k:{r.get('code') for r in rr[k] if r.get('code')} for k in KEYS}
    relations=event_pool_relation(sets)
    overlap=set(relations['conflicting_codes'])
    for c,row in tm.items():
        if complete(meta['limit_up'],d):
            row['is_limit_up']=c in sets['limit_up']
            if not row['is_limit_up']:row['board']=0
        if complete(meta['limit_down'],d):row['is_limit_down']=c in sets['limit_down']
        if complete(meta['open_board'],d) and complete(meta['limit_up'],d):
            row['touched_limit_up']=c in sets['open_board'] or c in sets['limit_up']
        if row.get('is_limit_up') is True:
            row['touched_limit_up']=True;row['is_limit_down']=False
        if c in overlap:
            row['record_conflict']=True
            row.setdefault('record_conflict_reasons',[]).append('INCOMPATIBLE_EVENT_POOL_MEMBERSHIP')
        if c in relations['compatible_overlap_codes']:
            row['event_membership_note']='UPPER_TOUCH_THEN_LOWER_CLOSE_ALLOWED_NOT_A_CONFLICT'
        if row.get('record_conflict'):
            row.update(source_date=None,date_verified=False,closing_verified=False)
    prior=rr['previous_limit_up']
    if complete(meta['previous_limit_up'],p):
        for row in prior:
            row.update(is_limit_up=True,date_verified=True,closing_verified=True)
    try:
        proofs=collect_candidates(data,identities,cal_meta,policy=validation_policy,fetch=candidate_supplier)
    except Exception as exc:
        proofs={'status':'ERROR','records':{},'requests':{},'error':str(exc),
                'price_replacement':False,'full_market_proven':False}
    pm={r.get('code'):r for r in prior}
    for c,proof in proofs.get('records',{}).items():
        if proof.get('status')!='VALID':continue
        for which,row in [('current',tm.get(c)),('previous',pm.get(c))]:
            det=proof.get(which) or {}
            if row is None or row.get('record_conflict') or det.get('status')!='VALID':continue
            if cents(row.get('close'))!=cents(det.get('daily_close')):continue
            row.update(source_date=det['source_date'],date_verified=True,closing_verified=True,
                       is_limit_up=det['close_limit_up'],open_at_limit=det['open_at_limit_up'])
            row['individual_quote_evidence']={'method':proof.get('method'),'available_at':proof.get('available_at'),
                'proof_pointer':'/candidate_quote_evidence/records/'+c+'/'+which}
    valid_current=[k for k in KEYS if k!='previous_limit_up' and final(meta[k],d)]
    all_current=all(complete(meta[k],d) for k in KEYS if k!='previous_limit_up') and not conflicts and not overlap
    availability=[meta[k].get('available_at',meta[k].get('retrieved_at')) for k in valid_current]
    availability=[x for x in availability if isinstance(x,str)]
    current_meta={'source':'EXISTING_EASTMONEY_CORE_PRICE_UNION','scope':'PUBLIC_METRIC_EFFECTIVE_COHORTS',
        'status':'VALID' if all_current else 'PARTIAL' if valid_current else 'DATA_PENDING',
        'source_date':d if valid_current else None,'date_verified':bool(valid_current),
        'closing_verified':bool(valid_current),'complete':all_current,
        'full_market_breadth_proven':False,'full_market_price_universe':False,
        'as_of':d[:4]+'-'+d[4:6]+'-'+d[6:]+'T15:00:00+08:00' if valid_current else None,
        'available_at':max(availability) if availability else None,
        'pool_dependencies':[k for k in KEYS if k!='previous_limit_up'],
        'note':'Sparse event/prior-performance union only; not all A-share price records.'}
    native=parse_native(getattr(data,'market_breadth_raw',None),d,cal_meta)
    be=deepcopy(batch_evidence)
    be.setdefault('proofs',{})['market']={'status':'NOT_REQUESTED_BY_APPROVED_POLICY',
        'method':'FULL_MARKET_SPOT_DISABLED','complete':False,'full_market_prices_requested':False}
    be['proofs']['market_breadth']={k:deepcopy(v) for k,v in native.items() if k!='raw'}
    receipts=deepcopy(meta)
    receipts['market']={'interface':'FULL_MARKET_SPOT_DISABLED','status':'NOT_REQUESTED_BY_APPROVED_POLICY',
        'source_date':None,'date_verified':False,'closing_verified':False,'complete':False,
        'retrieved_at':native.get('available_at'),'record_count':0}
    receipts['market_breadth']={**{k:deepcopy(v) for k,v in native.items() if k!='raw'},
        'interface':'stock_market_activity_legu','retrieved_at':native.get('available_at')}
    raw_native=native.get('raw') or {}
    fi=capture_frame_inputs(data)
    fi['market_breadth_raw']={**deepcopy(raw_native.get('table',{'columns':['item','value'],'data':[]})),
        'status':raw_native.get('status','NOT_RETURNED'), 'attrs':{'source':SOURCE,'scope':SCOPE,
        'captured_at':raw_native.get('captured_at'),'table_sha256':raw_native.get('table_sha256')}}
    result={'date':d,'previous_date':p,'calendar':cal_meta,'collection_mode':MODE,
        'input_kind':getattr(data,'input_kind','LIVE_POOL_SCOPE_WITH_LEGU_NATIVE'),
        'today_records':list(tm.values()),'previous_records':prior,
        'source_meta':{'today':current_meta,'previous':meta['previous_limit_up'],'breadth':receipts['market_breadth']},
        'market_breadth':native,'acquisition_receipts':receipts,'batch_close_evidence':be,
        'primary_883900':fetch_ths_883900(d,p,supplier=primary_supplier),
        'candidate_quote_evidence':proofs,'frame_inputs':fi,
        'frame_capture_layer':'POST_EXISTING_FETCHER_BEFORE_APPROVED_POLICY_NOT_HTTP_RESPONSE',
        'security_master_inputs':master_captures,'diagnostics':diagnostics,
        'core_record_conflicts':conflicts,
        'event_pool_overlap_codes':relations['all_overlap_codes'],
        'event_pool_conflict_codes':relations['conflicting_codes'],
        'event_pool_compatible_overlap_codes':relations['compatible_overlap_codes'],
        'event_pool_relationships':relations,
        'market_data_scope':{'full_market_spot_requested':False,'full_market_stock_rows':0,
            'core_union_count':len(tm),'core_union_not_full_market':True,
            'breadth_source':SOURCE,'breadth_scope':SCOPE,'full_market_median_available':False},
        'security_master_identity_summary':{'resolved':sum(r.get('market_board') not in ('UNKNOWN','CONFLICT') for r in identities.values()),
            'unknown':sum(r.get('market_board')=='UNKNOWN' for r in identities.values()),
            'conflicts':[c for c,r in identities.items() if r.get('identity_conflict') or r.get('listing_date_conflict')]}}
    result['source_evidence_gaps']=[{'interface':k,'status':m.get('status'),
        'missing':m.get('issues',[]) or m.get('evidence_issues',[]) or ['DATE_FINALITY_OR_COMPLETENESS']}
        for k,m in receipts.items() if k!='market' and not complete(m,p if k=='previous_limit_up' else d)]
    data.policy_bundle=result
    return result


def apply_context(bundle,base):
    """Calculate each LOCAL metric from its own pool; breadth stays independent."""
    if bundle.get('collection_mode')!=MODE:return base
    d,p=bundle['date'],bundle['previous_date'];result=deepcopy(base)
    cal=TradeCalendar(bundle['calendar'].get('dates',[]),verified=bundle['calendar'].get('verified') is True)
    rec=bundle.get('acquisition_receipts',{});raw=bundle.get('frame_inputs',{})
    from core.approved_data_adapter import _restore_frame,normalize_frame
    tm={r.get('code'):r for r in bundle.get('today_records',[])}
    prior=bundle.get('previous_records',[]);pm={r.get('code'):r for r in prior}
    evidence={};scopes={};members={};oks={}
    for key in KEYS:
        spec=raw.get(key,{})
        codes=[]
        if spec:
            from core.input_contracts import find_column,normalize_code
            f=_restore_frame(spec);cc=find_column(f,['代码','股票代码','证券代码','code'])
            if cc:codes=[normalize_code(v) for v in f[cc]]
        idx=pm if key=='previous_limit_up' else tm;date=p if key=='previous_limit_up' else d
        seq=[idx.get(c,{'code':c}) for c in codes]
        sc=filter_scope(seq,date,cal);scopes[key]=sc;members[key]=sc['records']
        oks[key]=complete(rec.get(key,{}),date) and not sc['unknown_codes'] and not sc['conflicts']
    def proof(keys,valid,issues=None):
        times=[rec.get(k,{}).get('available_at') or rec.get(k,{}).get('retrieved_at') for k in keys]
        times=[x for x in times if isinstance(x,str)]
        return {'status':'VALID' if valid else 'DATA_PENDING','date_verified':bool(valid),
            'closing_verified':bool(valid),'complete':bool(valid),'source_date':d if valid else None,
            'source_dates':[d,p] if 'previous_limit_up' in keys else [d],
            'scope':'PUBLIC_METRIC_EFFECTIVE_COHORTS','source':'EXISTING_EASTMONEY_EVENT_AND_PERFORMANCE_POOLS',
            'available_at':max(times) if times else None,'pool_dependencies':keys,
            'full_market_breadth_proven':False,'unresolved_pools':[k for k in keys if not oks[k]],
            'issues':issues or []}
    u,dn,z=(members[k] for k in ('limit_up','limit_down','open_board'))
    # Old frozen bundles keep their old blocked status.  Only a newly built
    # bundle explicitly classifies compatible overlaps; no historical rewriting.
    overlap=set(bundle.get('event_pool_conflict_codes',bundle.get('event_pool_overlap_codes',[])))
    for key in ('limit_up','limit_down','open_board'):
        if overlap & {r['code'] for r in members[key]}:oks[key]=False
    counts=deepcopy(base['counts'])
    counts.update(up=len(u) if oks['limit_up'] else None,down=len(dn) if oks['limit_down'] else None,
        status='VALID' if oks['limit_up'] and oks['limit_down'] else 'PARTIAL' if oks['limit_up'] or oks['limit_down'] else 'DATA_PENDING',
        source_scope='APPROVED_LOCAL_EVENT_POOLS',full_market_breadth_proven=False,
        up_status='VALID' if oks['limit_up'] else 'DATA_PENDING',down_status='VALID' if oks['limit_down'] else 'DATA_PENDING')
    result['counts']=counts
    result['pool_scopes']=scopes
    for key in ('limit_up','limit_down'):evidence[key]=proof([key],oks[key])
    union=sorted({r['code'] for r in u+z})
    rate_valid=oks['limit_up'] and oks['open_board']
    result['failed_limitup_rate']={'name':'failed_limitup_rate','unit':'%',
        'value':len(z)/len(union)*100 if rate_valid and union else None,
        'status':'VALID' if rate_valid and union else 'EMPTY_EFFECTIVE' if rate_valid else 'DATA_PENDING',
        'numerator':len(z),'denominator':len(union),'numerator_codes':sorted(r['code'] for r in z),
        'denominator_codes':union,'unknown_codes':scopes['open_board']['unknown_codes']}
    evidence['failed_limitup_rate']=proof(['limit_up','open_board'],result['failed_limitup_rate']['status']=='VALID')
    hm={**rec.get('limit_up',{}),'scope':'APPROVED_LOCAL','complete':oks['limit_up']}
    result['highest_board']=highest_board_2b(u,hm,d,cal)
    result['known_ladder']=dict(Counter(r.get('board') for r in u if board_count(r.get('board')) is not None))
    result['ladder_status']='VALID' if oks['limit_up'] else 'DATA_PENDING'
    evidence['highest_board']=proof(['limit_up'],result['highest_board']['status']=='VALID')
    usable_rows=[r for r in tm.values() if r.get('source_date')==d and not r.get('record_conflict')]
    def calculate(kind='continuation',minimum=None,exact=None):
        selected=[r for r in scopes['previous_limit_up']['records'] if r.get('is_limit_up') is True
            and (minimum is None or (board_count(r.get('board')) is not None and r['board']>=minimum))
            and (exact is None or r.get('board')==exact)]
        # A missing member under a failed/incomplete performance source is a
        # source error, NOT permission to shrink the denominator after failure.
        missing=[r['code'] for r in selected if r['code'] not in tm or tm[r['code']].get('source_date')!=d
                 or tm[r['code']].get('record_conflict')]
        unknown_state=[r['code'] for r in selected if r['code'] in tm and
            ((kind=='mean_change' and number(tm[r['code']].get('change_pct')) is None) or
             (kind!='mean_change' and boolean(tm[r['code']].get('is_limit_up')) is None))]
        # A genuine contradiction is not permission to subtract that stock
        # from an otherwise complete cohort.  Keep source failures/conflicts
        # distinguishable from a successful response with an absent member.
        conflicting=[r['code'] for r in selected if r['code'] in tm
                     and tm[r['code']].get('record_conflict')]
        source_error=bool(conflicting) or (bool(missing or unknown_state)
                    and not complete(rec.get('previous_pool_performance',{}),d))
        if kind!='mean_change' and not oks['limit_up']:source_error=True
        tmeta={'status':'ERROR' if source_error else 'VALID',
            'source_date':d,'date_verified':not source_error,'closing_verified':not source_error,
            'complete':False,'scope':'PREVIOUS_COHORT_OBSERVATIONS_NOT_FULL_MARKET'}
        m=cohort_metric(prior,usable_rows,p,d,cal,kind=kind,today_meta=tmeta,
            prior_meta={**rec.get('previous_limit_up',{}),'complete':oks['previous_limit_up']},
            board_min=minimum,board_exact=exact)
        m['source_scope']='APPROVED_LOCAL_PREVIOUS_COHORT'
        if source_error:m['upstream_source_blockers']={'missing_codes':missing,'unknown_state_codes':unknown_state,
              'conflicting_codes':conflicting,
              'previous_performance_status':rec.get('previous_pool_performance',{}).get('status')}
        return m
    result['continuation']=calculate()
    result['high_board_fail_rate']=calculate('failure',minimum=4)
    result['promotions']={str(k):calculate('promotion',exact=k) for k in range(1,max(5,max((board_count(r.get('board')) or 0 for r in prior),default=0))+1)}
    result['yesterday_performance']=select_yesterday_performance(bundle.get('primary_883900'),calculate('mean_change'),d)
    for name,keys in [('continuation',['previous_limit_up','limit_up','previous_pool_performance']),
        ('high_board_fail_rate',['previous_limit_up','limit_up','previous_pool_performance']),
        ('yesterday_performance',['previous_limit_up','previous_pool_performance'])]:
        valid=result[name].get('status')=='VALID'
        evidence[name]=proof(keys,valid)
        if name=='yesterday_performance' and result[name].get('source')=='THS_883900':
            evidence[name].update(source='THS_883900',pool_dependencies=[],unresolved_pools=[],
                issues=['PROVIDER_NATIVE_MEAN_NOT_LOCAL_SCOPE_EQUIVALENCE'])
    for k,m in result['promotions'].items():evidence['rate'+k+str(int(k)+1)]=proof(
        ['previous_limit_up','limit_up','previous_pool_performance'],m['status']=='VALID')
    native=bundle.get('market_breadth',{})
    # Reparse saved raw provider result so a manually edited status is not proof.
    parsed=parse_native(native.get('raw'),d,bundle.get('calendar',{}))
    # Historical native collection is intentionally not re-requested.  If a
    # same-day validated aggregate was already persisted, use that narrow fact
    # for scoring and publication; never substitute a later trading day.
    if parsed.get('status') != 'VALID':
        try:
            from pathlib import Path
            from collection.market_breadth_store import read as read_market_breadth, read_import as read_market_breadth_import
            fact_db = Path(__file__).resolve().parent / 'data' / '.migration_shadow' / 'market_store_5535.next.sqlite3'
            fact = read_market_breadth(fact_db, d)
            if fact and fact.get('status') == 'VALID' and str(fact.get('source_date') or d) == d:
                import_evidence = read_market_breadth_import(fact_db, fact.get('source_batch_id'))
                parsed = {
                    **parsed,
                    'status': 'VALID', 'complete': True,
                    'up': fact.get('up_count'), 'down': fact.get('down_count'),
                    'flat': fact.get('flat_count'), 'unknown': fact.get('unknown_count', 0),
                    'total': sum(int(fact.get(key) or 0) for key in ('up_count', 'down_count', 'flat_count', 'unknown_count')),
                    'source': fact.get('source') or SOURCE,
                    'source_date': d, 'as_of': fact.get('as_of'),
                    'source_batch_id': fact.get('source_batch_id'),
                    'validation_evidence': {'import': import_evidence} if import_evidence else None,
                    'date_verified': True, 'closing_verified': True,
                    'issues': [], 'request_status': 'PERSISTED_VALIDATED_FACT',
                    'validation_method': 'PERSISTED_NARROW_BREADTH_FACT',
                }
        except Exception:
            pass
    result['breadth']={k:deepcopy(v) for k,v in parsed.items() if k!='raw'}
    result['metric_evidence']=evidence
    result['breadth_scope_change']={'source':SOURCE,'scope':SCOPE,'local_filters_applied':False,
        'other_metrics_scope':'APPROVED_LOCAL_UNCHANGED','full_market_median_available':False}
    result['collection_mode']=MODE
    return result
