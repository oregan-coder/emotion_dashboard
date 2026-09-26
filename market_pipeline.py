"""Actual integration of approved rules into the existing data/model/snapshot path.
`policy_bundle` is normalized evidence, NOT an alternative dashboard/site.
"""
from __future__ import annotations
from collections import Counter
import pandas as pd
from input_contracts import find_column, normalize_code, integer, number, boolean, board_count
from approved_policy import (TradeCalendar, day, filter_scope, cohort_metric,
    highest_board_2b, select_yesterday_performance, two_open_limit_filter,
    today_counts, source_usable, RULE_VERSION, index_records)


def _subset(frame, codes):
    if frame is None or not hasattr(frame, 'columns'):
        return None
    column=find_column(frame,['代码','股票代码','证券代码','code'])
    if column is None:
        result=frame.iloc[0:0].copy();result.attrs['status']='INVALID_SCHEMA';return result
    result=frame.loc[frame[column].map(normalize_code).isin(set(codes))].copy()
    result.attrs.update(frame.attrs)
    return result


def build_context(bundle):
    date=day(bundle.get('date'));prior_date=day(bundle.get('previous_date'))
    cal_spec=bundle.get('calendar',{})
    cal=TradeCalendar(cal_spec.get('dates',[]),verified=cal_spec.get('verified') is True,source=cal_spec.get('source',''))
    prior=list(bundle.get('previous_records',[]));today=list(bundle.get('today_records',[]))
    meta=dict(bundle.get('source_meta',{}));tmeta=meta.get('today',{});pmeta=meta.get('previous',{})
    # Do not allow a non-adjacent prior day to silently replace yesterday.
    prior_adjacent=cal.previous(date)==prior_date and prior_date is not None
    if not prior_adjacent:
        pmeta={**pmeta,'status':'DATE_MISMATCH','complete':False}
    common=dict(prior_records=prior,today_records=today,prior_date=prior_date,observation=date,
                calendar=cal,today_meta=tmeta,prior_meta=pmeta)
    continuation=cohort_metric(**common)
    performance=cohort_metric(**common,kind='mean_change')
    high_fail=cohort_metric(**common,kind='failure',board_min=4)
    promotion={str(k):cohort_metric(**common,kind='promotion',board_exact=k) for k in range(1,max(5,max((board_count(r.get('board')) or 0 for r in prior),default=0))+1)}
    counts=today_counts(today,tmeta,date,cal)
    scoped=counts['scope'];accepted=scoped['records']
    limit_rows=[r for r in accepted if boolean(r.get('is_limit_up')) is True]
    height=highest_board_2b(limit_rows,{
        **tmeta, 'scope':'APPROVED_LOCAL',
        'complete':tmeta.get('complete') is True and counts['status']=='VALID'},date,cal)
    # Whole-market open-board rate is a different population from high-board failures.
    attempted=[];open_unknown=[];open_failed=[]
    for r in accepted:
        up=boolean(r.get('is_limit_up'));touched=boolean(r.get('touched_limit_up'))
        if up is True:attempted.append(r['code'])
        elif touched is True and up is False:
            attempted.append(r['code']);open_failed.append(r['code'])
        elif up is None or touched is None:open_unknown.append(r['code'])
    market_valid=counts['status']=='VALID'
    failed_rate={'value':len(open_failed)/len(attempted)*100 if attempted and not open_unknown and market_valid else None,
                 'numerator':len(open_failed),'denominator':len(attempted),'numerator_codes':sorted(open_failed),
                 'denominator_codes':sorted(attempted),'unknown_codes':open_unknown,
                 'status':'VALID' if attempted and not open_unknown and market_valid else 'DATA_PENDING',
                 'unit':'%','name':'failed_limitup_rate'}
    prior_map,_,_=index_records(prior)
    candidate_filter={r['code']:two_open_limit_filter(prior_map.get(r['code']),r,prior_date,date)
                      for r in limit_rows if board_count(r.get('board'))==2}
    market_changes=[number(r.get('change_pct')) for r in accepted]
    breadth_complete=market_valid and all(x is not None for x in market_changes)
    breadth={'up':sum(x>0 for x in market_changes) if breadth_complete else None,
             'down':sum(x<0 for x in market_changes) if breadth_complete else None,
             'flat':sum(x==0 for x in market_changes) if breadth_complete else None,
             'unknown':sum(x is None for x in market_changes),
             'status':'VALID' if breadth_complete else 'DATA_PENDING'}
    context = {'rule_version':RULE_VERSION,'date':date,'previous_date':prior_date,
            'prior_date_adjacent':prior_adjacent,'scope':scoped,'counts':counts,'breadth':breadth,
            'continuation':continuation,'yesterday_performance':select_yesterday_performance(bundle.get('primary_883900'),performance,date),
            'high_board_fail_rate':high_fail,'promotions':promotion,'failed_limitup_rate':failed_rate,
            'highest_board':height,'candidate_filter':candidate_filter,
            'source_meta':meta,'calendar':{'verified':cal.verified,'source':cal.source},
            'known_ladder':dict(Counter(board_count(r.get('board')) for r in limit_rows if board_count(r.get('board')) is not None)),
            'five_day_cycle_status':'PAUSED_BY_USER'}
    from public_metric_evidence import metric_overrides
    result=metric_overrides(bundle, context)
    from pool_scoped_runtime import apply_context as apply_pool_scoped_context
    result=apply_pool_scoped_context(bundle,result)
    from smash_dynamic import make_universe
    result['smash_universe']=make_universe(bundle,result)
    return result


def apply_context(data, bundle):
    """Attach lineage, preserve original frames, then consistently filter local consumers."""
    ctx=build_context(bundle)
    data.policy_context=ctx
    data.raw_frames={name:getattr(data,name,None) for name in ('market','limit_up','limit_down','open_board','previous_limit_up')}
    accepted=ctx['scope']['eligible_codes']
    data.scope_stat_frames={name:_subset(getattr(data,name,None),accepted)
                           for name in ('market','limit_up','limit_down','open_board')}
    for name in ('market','limit_up','limit_down','open_board'):
        setattr(data,name,data.scope_stat_frames[name])
    # Unknown scope is not silently treated as excluded. Keep identifiable two-board
    # candidates visible but blocked; approved statistics only use known eligibility.
    data.limit_up=_subset(data.raw_frames['limit_up'], accepted + ctx['scope']['unknown_codes'])
    identities={normalize_code(r.get('code')):r for r in bundle.get('today_records',[])}
    if isinstance(data.limit_up,pd.DataFrame) and not data.limit_up.empty:
        code_col=find_column(data.limit_up,['代码','股票代码','证券代码','code'])
        if code_col:
            data.limit_up['market_board']=[identities.get(normalize_code(c),{}).get('market_board') for c in data.limit_up[code_col]]
            data.limit_up['market_board_evidence']=[identities.get(normalize_code(c),{}).get('market_board_evidence') for c in data.limit_up[code_col]]
    for code in ctx['scope']['unknown_codes']:
        ctx['candidate_filter'][code]={'status':'UNKNOWN','reason':'ST/上市日期/日期或范围证据不足',
                                       'rule':'SCOPE_EVIDENCE','remove_from_market_statistics':False}
    prior_codes=ctx['continuation']['scope']['eligible_codes']
    data.previous_limit_up=_subset(getattr(data,'previous_limit_up',None),prior_codes)
    # A failed scope lookup is not a genuinely empty market/candidate universe.
    data.policy_unknown_records=ctx['scope']['unknown_codes']
    data.candidate_filter_evidence=ctx['candidate_filter']
    return ctx


def overlay_smash(smash, context):
    """Keep legacy engine diagnostics, use only approved population rates as active input."""
    raw={k:getattr(smash,k,None) for k in ('score','state','highest_board','break_rate','rate12','rate23','rate34','rate45','rate56')}
    smash.legacy_unvalidated=raw
    for k in (1,2,3,4,5):
        setattr(smash,f'rate{k}{k+1}',context['promotions'][str(k)]['value'])
    high=context['high_board_fail_rate']
    smash.break_rate=high['value'] # compatibility alias; never used as whole-market open rate
    smash.high_board_fail_rate=high['value']
    smash.failed_limitup_rate=context['failed_limitup_rate']['value']
    smash.highest_board=context['highest_board']['value']
    smash.high_count=high['denominator'] if high['status']=='VALID' else None
    smash.high_break_count=high['numerator'] if high['status']=='VALID' else None
    smash.high_continue_count=(high['denominator']-high['numerator']) if high['status']=='VALID' else None
    smash.high_loss_count=smash.high_break_count
    from smash_engine import _judge_high_feedback
    from smash_dynamic import overlay
    overlay(smash,context)
    smash.high_feedback=(_judge_high_feedback({'high_count':smash.high_count,'break':smash.high_break_count})
                         if smash.high_count is not None else '待证据')
    return smash
