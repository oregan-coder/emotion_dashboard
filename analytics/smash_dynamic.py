"""5535 approved dynamic-tier smash score. Pure, no requests and no DB writes.
Approval: k=2..prior highest, ratio sum / 4 * 10; confirmed empty tiers
are omitted; effective all-failure zero is included. Never turn source errors
into empty layers. Legacy engine/classification file remains immutable.
"""
from __future__ import annotations
from copy import deepcopy
from math import isfinite, fsum
VERSION='5535_SMASH_DYNAMIC_DIV4_V1'

def num(x):
    if x is None or isinstance(x,bool):return None
    try:y=float(x)
    except (ValueError,TypeError,OverflowError):return None
    return y if isfinite(y) else None

def integer(x):
    y=num(x)
    return int(y) if y is not None and y>=0 and y==int(y) else None

def make_universe(bundle,context):
    from core.approved_policy import TradeCalendar,filter_scope,source_usable
    from core.input_contracts import board_count,boolean
    p=bundle.get('previous_date');d=bundle.get('date'); cs=bundle.get('calendar') or {}
    cal=TradeCalendar(cs.get('dates',[]),verified=cs.get('verified') is True,source=cs.get('source',''))
    pm=(bundle.get('acquisition_receipts') or {}).get('previous_limit_up') or (bundle.get('source_meta') or {}).get('previous') or {}
    scope=filter_scope(bundle.get('previous_records',[]),p,cal)
    issues=[]
    if cal.previous(d)!=p:issues.append('PRIOR_TRADE_DATE_NOT_ADJACENT')
    if not source_usable(pm,p) or pm.get('complete') is not True or pm.get('closing_verified') is not True:
        issues.append('PRIOR_POOL_DATE_CLOSE_OR_COMPLETENESS_UNVERIFIED')
    if scope.get('unknown_codes') or scope.get('conflicts'):issues.append('PRIOR_SCOPE_UNKNOWN_OR_CONFLICT')
    rows=[]
    for r in scope['records']:
        if boolean(r.get('is_limit_up')) is not True:
            issues.append('PRIOR_LIMITUP_MEMBERSHIP_UNVERIFIED:'+str(r.get('code')));continue
        b=board_count(r.get('board'))
        if b is None or b<1:issues.append('PRIOR_BOARD_UNVERIFIED:'+str(r.get('code')));continue
        rows.append((r['code'],b))
    highest=max([b for _,b in rows],default=0)
    return {'confirmed':not issues,'highest_board':highest if not issues else None,
        'observed_highest_board':highest,'date':p,'observation_date':d,'issues':sorted(set(issues)),
        'member_count':len(rows),'tier_counts':{str(b):sum(bb==b for _,bb in rows) for b in sorted({bb for _,bb in rows})},
        'approved_scope_excluded_codes':scope.get('excluded_codes',[]),
        'unknown_codes':scope.get('unknown_codes',[]),'complete_prior_pool_required':True}

def score(context):
    u=deepcopy(context.get('smash_universe') or {})
    out={'version':VERSION,'formula':'sum(valid_tier_ratio_decimal)/4*10','divisor':4,'multiplier':10,
         'first_tier':2,'prior_highest_board':u.get('highest_board'),'universe':u,'score':None,'score_raw':None,
         'state':'待证据','status':'DATA_PENDING','included_group_count':0,'observed_layer_count':0,
         'no_sample':False,'tiers':[],'missing_inputs':[], 'omitted_layers':[], 'valid_zero_layers':[],
         'depends_on_emotion_score':False,'enabled':False,'strategy_status':'NOT_ENABLED'}
    h=integer(u.get('highest_board'))
    if u.get('confirmed') is not True or h is None:
        out['missing_inputs']=['PRIOR_HIGHEST_OR_COHORT_NOT_CONFIRMED']+u.get('issues',[]);return out
    # A corrupt input must not launch an unbounded loop. This is not a scoring ceiling.
    if h>10000:out['missing_inputs']=['INVALID_BOARD_HEIGHT'];return out
    all_promos=context.get('promotions') or {}; ratios=[]
    for k in range(2,h+1):
        m=all_promos.get(str(k)) or {};o=integer(m.get('original_count'));e=integer(m.get('effective_count',m.get('denominator')));n=integer(m.get('numerator'))
        row={'from_board':k,'to_board':k+1,'label':f'{k}进{k+1}','original_count':o,
             'effective_count':e,'numerator':n,'removed':deepcopy(m.get('removed') or []),
             'metric_status':m.get('status'),'ratio_pct':m.get('value'),'ratio_decimal':None,
             'included':False,'status':'PENDING','reason':None}
        v=num(m.get('value'));status=m.get('status')
        removed_count=integer(m.get('removed_count',len(row['removed'])))
        counts_ok=(o is not None and e is not None and n is not None and removed_count is not None
                   and n<=e<=o and removed_count==o-e)
        fatal=bool(m.get('upstream_source_blockers') or m.get('today_conflicts'))
        if status=='VALID' and counts_ok and e>0 and v is not None and 0<=v<=100 and not fatal and abs(v-n/e*100)<1e-7:
            row.update(included=True,status='INCLUDED_ZERO' if n==0 else 'INCLUDED',ratio_decimal=n/e)
            ratios.append(n/e)
            if n==0:out['valid_zero_layers'].append(row['label'])
        elif status=='EMPTY_EFFECTIVE' and counts_ok and o==0 and e==0 and not row['removed'] and not fatal:
            row.update(status='OMITTED_NO_ORIGINAL_SAMPLE',reason='CONFIRMED_ABSENT_PRIOR_LAYER')
            out['omitted_layers'].append(row['label'])
        elif status=='EMPTY_EFFECTIVE' and counts_ok and o>0 and e==0 and len(row['removed'])==o and not fatal and all(
            'SUSPENDED' in r.get('reasons',[]) and set(r['reasons'])<={'SUSPENDED','CHANGE_PCT_MISSING','CLOSE_LIMIT_STATE_MISSING','TODAY_CONSECUTIVE_BOARD_MISSING'} for r in row['removed']):
            row.update(status='OMITTED_ALL_SUSPENDED',reason='ALL_MEMBERS_CONFIRMED_SUSPENDED')
            out['omitted_layers'].append(row['label'])
        else:
            row['reason']='SOURCE_OR_COHORT_PENDING' if status not in ('VALID','EMPTY_EFFECTIVE') or fatal else 'COUNTS_OR_EMPTY_REASON_UNPROVEN'
            out['missing_inputs'].append(row['label']+':'+row['reason'])
        out['tiers'].append(row)
    out['observed_layer_count']=len(out['tiers']);out['included_group_count']=len(ratios)
    out['ratio_sum']=fsum(ratios)
    if not out['missing_inputs']:
        from analytics.smash_engine import _smash_state
        raw=fsum(ratios)/4*10
        out.update(score_raw=raw,score=round(raw,2),state=_smash_state(round(raw,2)),status='VALID',no_sample=not ratios)
    return out

def overlay(smash,context):
    """Apply the approved score; preserve per-layer raw rates and legacy diagnostics."""
    d=score(context);promos=context.get('promotions') or {}
    for k,m in promos.items():setattr(smash,f'rate{k}{int(k)+1}',m.get('value'))
    smash.rates={f'{k}_{int(k)+1}':{'rate':m.get('value'),'success':m.get('numerator'),
        'total':m.get('denominator'),'status':m.get('status')} for k,m in promos.items()}
    smash.score=d['score'];smash.state=d['state'];smash.smash_detail=d
    return smash
