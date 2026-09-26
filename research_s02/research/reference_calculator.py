"""S02 proposal calculator. Offline reference only; not a production plug-in.
No network/filesystem writes on import. Inputs must already use verified units and
approved cohorts. Synthetic evaluation is not validation of trading efficacy.
"""
from __future__ import annotations
import math
from numbers import Real, Integral
from typing import Any

WEIGHTS = {'A01':8,'A02':8,'A03':7,'A04':4,'A05':3,
           'B01':10,'B02':12,'B03':18,'C02':8,'D01':10,'D02':6,'D03':6}


def number(value: Any, name: str, lo: float | None = None,
           hi: float | None = None) -> float:
    if isinstance(value, bool) or type(value).__name__ in ('bool', 'bool_') or not isinstance(value, Real):
        raise ValueError(f'{name}: canonical finite numeric input required')
    result = float(value)
    if not math.isfinite(result) or (lo is not None and result < lo) or (hi is not None and result > hi):
        raise ValueError(f'{name}: out-of-range or nonfinite input')
    return result


def count(value: Any, name: str) -> int:
    if isinstance(value, bool) or type(value).__name__ in ('bool', 'bool_') or not isinstance(value, Integral) or value < 0:
        raise ValueError(f'{name}: nonnegative canonical integer required')
    return int(value)


def clip01(x: float) -> float:
    return min(1.0, max(0.0, x))


def b03(n1: Any, n2: Any, n3plus: Any, *, cohort_verified: bool = False) -> dict:
    """Counts exclude the current candidate. Unknown cohort/counts return null.
    'cohort_verified' is an input contract, not a claim verified by this function.
    """
    if cohort_verified is not True or any(x is None for x in (n1, n2, n3plus)):
        return {'score':None,'parts':None,'status':'INPUT_PENDING','max':18}
    a,b,c = count(n1,'n1'),count(n2,'n2'),count(n3plus,'n3plus')
    lower = 0 if a == 0 else 2 if a == 1 else 3 if a == 2 else 4 if a <= 4 else 6
    peer = min(b,3)
    upper = 0 if c == 0 else 2 if c == 1 else 3 if c == 2 else 4
    structure = 5 if a and b and c else 3 if a and c else 2 if a and b else 1 if b and c else 0
    parts = {'lower':lower,'peer':peer,'upper':upper,'structure':structure}
    return {'score':sum(parts.values()),'parts':parts,'status':'PROPOSAL_CALCULATED','max':18,
            'counts_excluding_candidate':{'n1':a,'n2':b,'n3plus':c}}


def calculate_reference(x: dict[str, Any], *, verified_ids: set[str] | None = None) -> dict:
    """Evaluate only explicitly verified item inputs; never normalise partial totals.
    verified_ids indicates the caller's evidence contract, not source validation.
    None/missing inputs remain pending. Invalid values are reported per item.
    """
    verified_ids = verified_ids or set()
    scores: dict[str, float | int | None] = {}
    errors: dict[str, str] = {}
    def ratio(a: str, *denominator: str) -> float:
        numerator=count(x[a],a)
        total=sum(count(x[k],k) for k in denominator)
        if total == 0:
            raise LookupError('zero denominator / NOT_APPLICABLE')
        return numerator/total
    def first_rank() -> float:
        n=count(x['n'],'n')
        if n < 2:
            raise LookupError('NOT_COMPARABLE: fewer than two ranked members')
        rank=number(x['rank'],'rank',1,n)
        return 8*(n-rank)/(n-1)
    functions = {
        'A01':lambda:8*clip01((number(x['r_pct'],'r_pct')+3)/8),
        'A02':lambda:8*clip01(number(x['p23'],'p23',0,1)/.5),
        'A03':lambda:7*(1-number(x['fail_high'],'fail_high',0,1)),
        'A04':lambda:4*ratio('U','U','Z'),
        'A05':lambda:3*ratio('U','U','D'),
        'B01':lambda:10*number(x['breadth'],'breadth',0,1),
        'B02':lambda:6*int(number(x['excess_median_T'],'excess_median_T')>0)+6*int(number(x['excess_median_previous'],'excess_median_previous')>0),
        'B03':lambda:b03(x['n1'],x['n2'],x['n3plus'],cohort_verified=True)['score'],
        'C02':first_rank,
        'D01':lambda:10*number(x['remaining_session_minutes'],'remaining_session_minutes',0,240)/240,
        'D02':lambda:6/(1+count(x['open_break_count'],'open_break_count')),
        'D03':lambda:6*clip01(number(x['seal_amount'],'seal_amount',0)/number(x['circulating_market_cap'],'circulating_market_cap',1e-12)/.01)
    }
    for key,fn in functions.items():
        if key not in verified_ids:
            scores[key]=None
            errors[key]='INPUT_PENDING: evidence/units/cohort not verified by caller'
            continue
        try:
            value=fn()
            if value is None:
                scores[key]=None; errors[key]='INPUT_PENDING: missing count'
            else:
                scores[key]=value
        except (KeyError, ValueError, LookupError, TypeError, ZeroDivisionError) as exc:
            scores[key]=None; errors[key]=f'{type(exc).__name__}: {exc}'
    known=sum(v for v in scores.values() if v is not None)
    complete=all(v is not None for v in scores.values())
    return {'version':'S02_WEIGHT_PROPOSAL_R1','enabled':False,'approval_status':'PENDING_USER_REVIEW',
        'strategy_status':'NOT_ENABLED','item_scores':scores,'known_subtotal':known,
        'research_score_proposal':known if complete else None,'missing_or_invalid':errors,
        'modules':{group:sum(v for k,v in scores.items() if k.startswith(group))
                   if all(v is not None for k,v in scores.items() if k.startswith(group)) else None for group in 'ABCD'},
        'final_score':None,'grade':None,'permission':None,
        'note':'Only formula arithmetic. Does not verify source dates, approved cohort construction, theme identity, trade eligibility or predictive performance.'}
