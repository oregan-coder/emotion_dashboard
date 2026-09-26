"""Executable USER-APPROVED 5535 input rules. No new score weights or thresholds.

Canonical records carry code/name/listing_date/source_date plus typed market
states. Source envelopes distinguish fetch success from date/completeness proof.
All exclusions are evidence, never silently discarded records.
"""
from __future__ import annotations
from datetime import datetime, date
from decimal import Decimal
from bisect import bisect_left, bisect_right
import re
from core.input_contracts import number, integer, boolean, normalize_code, board_count

RULE_VERSION = '5535_approved_input_rules_20260909_v2'
ALLOWED_BOARDS = {'SSE_MAIN_A','SZSE_MAIN_A','CHINEXT_A','STAR_A'}


def day(value):
    if isinstance(value, (date, datetime)):
        try: return value.strftime('%Y%m%d')
        except (ValueError,TypeError): return None
    if not isinstance(value, str):
        return None
    text = re.sub(r'[-/]', '', value.strip())
    try:
        return datetime.strptime(text, '%Y%m%d').strftime('%Y%m%d') if len(text) == 8 else None
    except ValueError:
        return None


class TradeCalendar:
    def __init__(self, dates, *, verified=False, source=''):
        self.dates = sorted({d for value in dates if (d := day(value))})
        self.verified = verified is True
        self.source = source

    def previous(self, observation):
        d = day(observation)
        if not self.verified or d not in self.dates:
            return None
        i = bisect_left(self.dates, d)
        return self.dates[i - 1] if i else None

    def age(self, listing_date, observation):
        start, end = day(listing_date), day(observation)
        if not self.verified or not start or not end or not self.dates or start > end:
            return None
        if end not in self.dates or start < self.dates[0]:
            return None
        # Listing date can be older than the first listed trading date only with
        # an independently verified full calendar; no weekdays-only fallback.
        if start not in self.dates:
            return None
        return bisect_right(self.dates, end) - bisect_left(self.dates, start)


def exchange_board(code):
    code = normalize_code(code)
    if code.startswith(('600','601','603','605')): return 'SSE_MAIN_A'
    if code.startswith(('000','001','002','003')): return 'SZSE_MAIN_A'
    if code.startswith(('300','301')): return 'CHINEXT_A'
    if code.startswith('688'): return 'STAR_A'
    if code.startswith('30'): return 'UNKNOWN'  # resolve via exchange master, never auto-admit
    return 'OUTSIDE'


def scope_decision(record, observation, calendar):
    code = normalize_code(record.get('code'))
    result = {'code':code,'sample_date':day(observation),'status':'UNKNOWN','reasons':[], 'trading_day_ordinal':None}
    if not code:
        result['reasons'] = ['INVALID_CODE'];return result
    board = record.get('market_board') or exchange_board(code)
    if board in ('UNKNOWN', 'CONFLICT'):
        result['reasons'] = ['BOARD_MASTER_UNVERIFIED_OR_CONFLICT'];return result
    if board not in ALLOWED_BOARDS:
        result.update(status='EXCLUDED',reasons=['OUTSIDE_APPROVED_A_SHARE_BOARDS']);return result
    # Risk status/name must be as of the sample date, not today's name for history.
    source_date = day(record.get('source_date'))
    if source_date != day(observation):
        result['reasons'] = ['SAMPLE_DATE_UNVERIFIED'];return result
    st = boolean(record.get('is_st'))
    name = record.get('name')
    if st is None and isinstance(name, str) and name.strip():
        st = 'ST' in name.upper()
    if st is True:
        result.update(status='EXCLUDED',reasons=['ST_OR_STAR_ST']);return result
    if st is None:
        result['reasons'] = ['ST_STATUS_UNKNOWN'];return result
    age = calendar.age(record.get('listing_date'), observation)
    result['trading_day_ordinal'] = age
    if age is None:
        result['reasons'] = ['LISTING_DATE_OR_CALENDAR_UNKNOWN'];return result
    if age <= 60:
        result.update(status='EXCLUDED',reasons=['NEW_LISTING_DAYS_1_TO_60']);return result
    result.update(status='ELIGIBLE',reasons=[])
    return result


def index_records(records):
    """Deduplicate identical records; conflicting duplicates become explicit unknown."""
    indexed, duplicates, conflicts = {}, [], []
    for record in records or []:
        r = dict(record);code = normalize_code(r.get('code'));r['code'] = code
        if not code:
            conflicts.append({'code':None,'reason':'INVALID_CODE','record':r});continue
        if code in indexed:
            duplicates.append(code)
            if indexed[code] != r:
                indexed[code] = {'code':code,'record_conflict':True}
                conflicts.append({'code':code,'reason':'CONFLICTING_DUPLICATE'})
        else:
            indexed[code] = r
    return indexed, sorted(set(duplicates)), conflicts


def filter_scope(records, observation, calendar):
    indexed, duplicates, conflicts = index_records(records)
    decisions = [scope_decision(r, observation, calendar) for r in indexed.values()]
    eligible = {r['code'] for r in decisions if r['status']=='ELIGIBLE'}
    return {'records':[indexed[c] for c in sorted(eligible)],'decisions':decisions,
            'original_codes':sorted(indexed),'eligible_codes':sorted(eligible),
            'unknown_codes':[r['code'] for r in decisions if r['status']=='UNKNOWN'],
            'excluded_codes':[r['code'] for r in decisions if r['status']=='EXCLUDED'],
            'duplicate_codes':duplicates,'conflicts':conflicts,'rule_version':RULE_VERSION}


def source_usable(meta, observation):
    return (isinstance(meta,dict) and meta.get('status') in ('VALID','PARTIAL')
            and meta.get('date_verified') is True
            and day(meta.get('source_date')) == day(observation))


def open_limit_state(row):
    explicit = boolean(row.get('open_at_limit'))
    if explicit is not None: return explicit
    op, lim = number(row.get('open'),minimum=0), number(row.get('limit_up_price'),minimum=0)
    if op is None or lim is None or op <= 0 or lim <= 0: return None
    return Decimal(str(op)) == Decimal(str(lim))


def two_open_limit_filter(prior, current, prior_date=None, observation=None):
    """Kleene logic: a known false proves NOT_EXCLUDED; otherwise unknown stays unknown."""
    prior, current = prior or {}, current or {}
    verified = ((prior_date is None or day(prior.get('source_date'))==day(prior_date))
                and (observation is None or day(current.get('source_date'))==day(observation)))
    vals = [open_limit_state(prior),boolean(prior.get('is_limit_up')),
            open_limit_state(current),boolean(current.get('is_limit_up'))] if verified else [None]*4
    if False in vals:
        state,reason='ALLOWED_BY_THIS_RULE','并非连续两日开盘涨停且收盘涨停；仅本条不排除'
    elif all(v is True for v in vals):
        state,reason='EXCLUDED','连续两日开盘即涨停且收盘涨停（含盘中炸板回封）'
    else:
        state,reason='UNKNOWN','两日开盘/收盘涨停证据不足或日期不匹配'
    return {'status':state,'reason':reason,'day_states':vals,'rule':'TWO_OPEN_LIMIT_DAYS',
            'remove_from_market_statistics':False,'prior_date':prior_date,'observation_date':observation}


def cohort_metric(prior_records, today_records, prior_date, observation, calendar, *, kind='continuation', today_meta=None, prior_meta=None, board_min=None, board_exact=None):
    """The user explicitly approved removing suspended/missing members from effective N."""
    scoped = filter_scope(prior_records, prior_date, calendar)
    today, duplicates, conflicts = index_records(today_records)
    original = []
    board_unknown = []
    membership_unknown = []
    for r in scoped['records']:
        prior_closed=boolean(r.get('is_limit_up'))
        if prior_closed is None: membership_unknown.append(r['code'])
        if prior_closed is not True: continue
        b = board_count(r.get('board'))
        if (board_min is not None or board_exact is not None) and b is None:
            board_unknown.append(r['code']);continue
        if board_min is not None and b < board_min: continue
        if board_exact is not None and b != board_exact: continue
        original.append(r['code'])
    effective, numerator, removed, changes = [], [], [], []
    globally_usable = source_usable(today_meta,observation) and source_usable(prior_meta,prior_date)
    cohort_known = not scoped['unknown_codes'] and not scoped['conflicts'] and not board_unknown and not membership_unknown
    # Missing yesterday membership cannot be inferred as absence. Require pool coverage proof.
    cohort_known = cohort_known and (prior_meta or {}).get('complete') is True
    for code in sorted(set(original)):
        row = today.get(code)
        reasons=[]
        if not globally_usable: reasons.append('SOURCE_FAILURE_OR_DATE_UNVERIFIED')
        if row is None or row.get('record_conflict'): reasons.append('TODAY_RECORD_MISSING_OR_CONFLICT')
        else:
            if day(row.get('source_date')) != day(observation): reasons.append('TODAY_DATE_UNVERIFIED')
            suspended = boolean(row.get('suspended'))
            if suspended is True: reasons.append('SUSPENDED')
            change = number(row.get('change_pct'))
            closed_up = boolean(row.get('is_limit_up'))
            if kind == 'mean_change':
                if change is None: reasons.append('CHANGE_PCT_MISSING')
            else:
                if closed_up is None: reasons.append('CLOSE_LIMIT_STATE_MISSING')
                if kind == 'promotion' and closed_up is True and board_count(row.get('board')) is None:
                    reasons.append('TODAY_CONSECUTIVE_BOARD_MISSING')
        if reasons:
            removed.append({'code':code,'reasons':list(dict.fromkeys(reasons))});continue
        effective.append(code)
        if kind == 'mean_change': changes.append(change)
        elif kind == 'failure':
            if not closed_up: numerator.append(code)
        elif kind == 'promotion':
            if closed_up and board_count(row.get('board')) == board_exact + 1: numerator.append(code)
        elif closed_up: numerator.append(code)
    count=len(effective)
    value=None
    if globally_usable and cohort_known and count:
        value=sum(changes)/count if kind=='mean_change' else len(numerator)/count*100
    status=('SOURCE_ERROR' if not globally_usable else 'DATA_PENDING' if not cohort_known else 'EMPTY_EFFECTIVE' if not count else 'VALID')
    return {'value':value,'status':status,'kind':kind,'unit':'%','source':'LOCAL_EFFECTIVE_COHORT',
            'original_count':len(set(original)),'effective_count':count,'denominator':count,
            'numerator':None if kind=='mean_change' else len(numerator),
            'sum_change_pct':sum(changes) if kind=='mean_change' and changes else None,
            'original_codes':sorted(set(original)),'effective_codes':effective,'numerator_codes':numerator,
            'removed':removed,'removed_count':len(removed),'coverage':count/len(original) if original else None,
            'scope':scoped,'unclassified_prior_membership':membership_unknown,'unclassified_board_codes':board_unknown,'today_duplicate_codes':duplicates,
            'today_conflicts':conflicts,'prior_date':prior_date,'observation_date':observation,
            'formula':'sum(change_pct)/effective_count' if kind=='mean_change' else 'numerator/effective_count*100',
            'rule_version':RULE_VERSION}


def highest_board_2b(records, meta, observation, calendar):
    scoped=filter_scope(records,observation,calendar)
    boards=[board_count(r.get('board')) for r in scoped['records'] if boolean(r.get('is_limit_up')) is True]
    observed=max((v for v in boards if v is not None),default=None)
    valid=(source_usable(meta,observation) and meta.get('complete') is True
           and bool(meta.get('as_of')) and meta.get('scope')=='APPROVED_LOCAL'
           and not scoped['unknown_codes'] and not scoped['conflicts']
           and all(b is not None for b in boards)
           and all(not r.get('as_of') or r.get('as_of')==meta.get('as_of') for r in scoped['records']))
    return {'value':observed if valid else None,'observed_subset_max':observed,
            'status':'VALID' if valid else 'DATA_PENDING','proof':dict(meta or {}),
            'scope':scoped,'method':'2B','rule_version':RULE_VERSION}


def select_yesterday_performance(primary, local, observation):
    primary = dict(primary or {})
    value=number(primary.get('value'))
    primary_ok=(str(primary.get('code'))=='883900' and primary.get('identity_verified') is True
                and source_usable(primary,observation) and primary.get('unit')=='%' and value is not None)
    if primary_ok:
        return {**primary,'value':value,'source':'THS_883900','local_scope_equivalence':'UNVERIFIED',
                'fallback_used':False,'rule_version':RULE_VERSION}
    return {**local,'source':'LOCAL_EFFECTIVE_PRIOR_LIMITUP_MEAN','fallback_used':True,
            'primary_attempt':primary,'rule_version':RULE_VERSION}


def today_counts(records, meta, observation, calendar):
    scoped=filter_scope(records,observation,calendar)
    rows=scoped['records'];unknown_up=[r['code'] for r in rows if boolean(r.get('is_limit_up')) is None]
    unknown_down=[r['code'] for r in rows if boolean(r.get('is_limit_down')) is None]
    usable=source_usable(meta,observation) and not scoped['unknown_codes'] and not scoped['conflicts'] and meta.get('complete') is True
    def count(k): return sum(boolean(r.get(k)) is True for r in rows)
    return {'up':count('is_limit_up') if usable and not unknown_up else None,
            'down':count('is_limit_down') if usable and not unknown_down else None,
            'observed_up':count('is_limit_up'),'observed_down':count('is_limit_down'),
            'unknown_up':unknown_up,'unknown_down':unknown_down,'scope':scoped,
            'status':'VALID' if usable and not unknown_up and not unknown_down else 'DATA_PENDING'}
