"""Offline S02-R1 adapter. Does not fetch data, calibrate rules, or write production.
The unchanged reference calculator evaluates arithmetic. This layer validates the
supplied evidence contract and exposes missingness and dated member composition.
Local hashes establish file identity, NOT independent confirmation of market facts.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timezone
from hashlib import sha256
import json
from pathlib import Path
from numbers import Real
import math
import re
from typing import Any

from reference_calculator import WEIGHTS, b03, calculate_reference, count, number

SCHEMA = '5535_S02_R1_INPUT_V1'
INPUT_TYPES = {'SYNTHETIC', 'CAPTURED_UNVERIFIED', 'CLOSING_EVIDENCE_SUPPLIED'}
UNITS = {
 'A01': {'r_pct': 'percent'}, 'A02': {'p23': 'fraction'},
 'A03': {'fail_high': 'fraction'}, 'A04': {'U': 'stocks', 'Z': 'stocks'},
 'A05': {'U': 'stocks', 'D': 'stocks'}, 'B01': {'breadth': 'fraction'},
 'B02': {'excess_median_T': 'percentage_points', 'excess_median_previous': 'percentage_points'},
 'B03': {'n1': 'stocks', 'n2': 'stocks', 'n3plus': 'stocks'},
 'C02': {'n': 'stocks', 'rank': 'average_rank'},
 'D01': {'remaining_session_minutes': 'minutes'},
 'D02': {'open_break_count': 'times'},
 'D03': {'seal_amount': 'CNY', 'circulating_market_cap': 'CNY'},
}
CODE = re.compile(r'^\d{6}$')
EXCLUSIONS = {'ST', 'NEW_LISTING_60_TRADING_DAYS', 'OUT_OF_APPROVED_SCOPE',
              'SUSPENDED', 'NECESSARY_DATA_MISSING'}


def json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(',', ':')).encode('utf-8')


def same_value(a: Any, b: Any) -> bool:
    # JSON 180 and 180.0 encode the same finite numeric value; bool is not numeric.
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, Real) and isinstance(b, Real):
        try:
            return math.isfinite(float(a)) and math.isfinite(float(b)) and a == b
        except (ValueError, OverflowError):
            return False
    return json_bytes(a) == json_bytes(b)


def parse_json(raw: bytes) -> Any:
    def reject(value: str) -> None:
        raise ValueError(f'Nonstandard JSON numeric value: {value}')
    return json.loads(raw.decode('utf-8-sig'), parse_constant=reject)


def pointer_value(obj: Any, pointer: str) -> Any:
    if pointer == '':
        return obj
    if not isinstance(pointer, str) or not pointer.startswith('/'):
        raise ValueError('JSON pointer must start with /')
    for token in pointer[1:].split('/'):
        token = token.replace('~1', '/').replace('~0', '~')
        obj = obj[int(token)] if isinstance(obj, list) else obj[token]
    return obj


def read_ref(ref: dict, base: Path, root: Path) -> Any:
    """Read only explicitly referenced JSON files below the selected evidence root."""
    path = (base / ref['file']).resolve()
    path.relative_to(root.resolve())
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != ref.get('sha256'):
        raise ValueError(f'EVIDENCE_HASH_MISMATCH: {ref.get("file")}')
    return pointer_value(parse_json(raw), ref.get('pointer', ''))


def _day(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError('ISO date required')
    return date.fromisoformat(value).isoformat()


def _timestamp(value: Any) -> datetime:
    out = datetime.fromisoformat(value)
    if out.tzinfo is None:
        raise ValueError('timezone-aware available_at/decision_asof required')
    return out


def remaining_minutes(value: str) -> float:
    """Approved PROPOSAL clock convention; not a proof of final close."""
    if not isinstance(value, str):
        raise ValueError('last seal clock must be a string')
    clock = time.fromisoformat(value)
    sec = clock.hour * 3600 + clock.minute * 60 + clock.second + clock.microsecond / 1e6
    if sec == 9 * 3600 + 25 * 60:
        return 240.0
    if 9.5 * 3600 <= sec <= 11.5 * 3600:
        return (11.5 * 3600 - sec) / 60 + 120
    if 13 * 3600 <= sec <= 15 * 3600:
        return (15 * 3600 - sec) / 60
    raise ValueError('SEAL_TIME_OUTSIDE_PROPOSAL_SESSION')


def observation_issues(obj: dict, synthetic: bool) -> list[str]:
    obs = obj.get('observation', {})
    issues = []
    try:
        today = _day(obs.get('trade_date'))
        prior = _day(obs.get('previous_trade_date'))
        if prior >= today:
            issues.append('PREVIOUS_TRADE_DATE_NOT_BEFORE_T')
    except (ValueError, TypeError):
        issues.append('OBSERVATION_DATE_INVALID')
    if synthetic:
        return issues
    for k in ['source_date_verified', 'closing_verified', 'previous_trade_date_verified']:
        if obs.get(k) is not True:
            issues.append(k.upper() + '_MISSING')
    try:
        cutoff = _timestamp(obs.get('decision_asof'))
        if cutoff.date().isoformat() != obs.get('trade_date'):
            issues.append('DECISION_CUTOFF_NOT_T')
    except (ValueError, TypeError):
        issues.append('DECISION_CUTOFF_INVALID')
    return issues


def review_issues(section: dict, obs: dict, synthetic: bool, base: Path,
                  root: Path, required_dates: list[str]) -> list[str]:
    issues = []
    if synthetic:
        return issues
    review = section.get('review', {})
    if review.get('status') != 'VERIFIED':
        issues.append('ITEM_EVIDENCE_NOT_VERIFIED')
    for k in ['units_verified', 'scope_verified', 'closing_verified']:
        if review.get(k) is not True:
            issues.append(k.upper() + '_MISSING')
    if review.get('source_dates') != required_dates:
        issues.append('ITEM_SOURCE_DATES_MISMATCH_OR_MISSING')
    try:
        if _timestamp(review.get('available_at')) > _timestamp(obs.get('decision_asof')):
            issues.append('FUTURE_INFORMATION_AFTER_DECISION_CUTOFF')
    except (ValueError, TypeError):
        issues.append('EVIDENCE_AVAILABILITY_TIME_UNKNOWN')
    refs = review.get('evidence_refs', [])
    if not isinstance(refs, list) or not refs:
        issues.append('EVIDENCE_REFS_MISSING')
    else:
        for ref in refs:
            try:
                read_ref(ref, base, root)
            except (KeyError, ValueError, TypeError, OSError, IndexError) as exc:
                issues.append('EVIDENCE_REF_INVALID:' + str(exc))
    return issues


def member_rows(section: dict, candidate: str, *, date_required: str,
                synthetic: bool, exclude_candidate: bool) -> tuple[list[dict], list[dict], list[str]]:
    """Never merge themes, infer a complete cohort, or silently discard unknowns."""
    issues, audit, selected, seen = [], [], [], {}
    theme = section.get('theme_id')
    if not isinstance(theme, str) or not theme.strip():
        issues.append('DATED_THEME_NOT_SELECTED')
    for k in ['membership_complete', 'theme_confirmed']:
        if section.get(k) is not True:
            issues.append(k.upper() + '_MISSING')
    rows = section.get('members')
    if not isinstance(rows, list):
        return [], audit, issues + ['MEMBERS_LIST_MISSING']
    for index, original in enumerate(rows):
        row = deepcopy(original)
        if not isinstance(row, dict):
            issues.append(f'ROW_{index}_NOT_OBJECT'); continue
        code = row.get('code')
        if not isinstance(code, str) or not CODE.fullmatch(code):
            issues.append(f'ROW_{index}_CODE_INVALID'); continue
        if exclude_candidate and code == candidate:
            audit.append({'code': code, 'action': 'REMOVE_CANDIDATE_SELF', 'row': index})
            continue
        if row.get('theme_id') != theme or row.get('trade_date') != date_required:
            issues.append(f'{code}:THEME_OR_DATE_MISMATCH'); continue
        if code in seen:
            # Source refs can differ; factual content must not conflict.
            comparable = lambda r: {k:v for k,v in r.items() if k not in ['source_ref', 'name']}
            if comparable(seen[code]) != comparable(row):
                issues.append(f'{code}:DUPLICATE_CONFLICT')
            else:
                audit.append({'code': code, 'action': 'DEDUP_IDENTICAL', 'row': index})
            continue
        seen[code] = row
        if row.get('selection') == 'EXCLUDED_APPROVED':
            reasons = row.get('exclusion_reasons', [])
            if not reasons or not set(reasons).issubset(EXCLUSIONS):
                issues.append(f'{code}:EXCLUSION_NOT_IN_APPROVED_POLICY')
            else:
                audit.append({'code': code, 'action': 'EXCLUDED_APPROVED', 'reasons': reasons})
            continue
        if row.get('selection') != 'INCLUDED':
            issues.append(f'{code}:SELECTION_UNKNOWN'); continue
        # The evidence contract must substantiate these row facts for captured data.
        if not synthetic and row.get('data_status') != 'VERIFIED':
            issues.append(f'{code}:MEMBER_DATA_UNVERIFIED'); continue
        selected.append(row)
    return selected, audit, issues


def derive_b03(section: dict, candidate: str, trade_date: str, synthetic: bool) -> dict:
    rows, audit, issues = member_rows(section, candidate, date_required=trade_date,
                                     synthetic=synthetic, exclude_candidate=True)
    groups = {'n1': [], 'n2': [], 'n3plus': []}
    for row in rows:
        try:
            height = count(row.get('board_count'), 'board_count')
            if row.get('close_limit_up') is not True or height < 1:
                raise ValueError('closing limit-up evidence inconsistent')
            key = 'n1' if height == 1 else 'n2' if height == 2 else 'n3plus'
            groups[key].append(row)
        except ValueError as exc:
            issues.append(f'{row["code"]}:INVALID_BOARD:{exc}')
    counts = {key:len(value) for key,value in groups.items()} if not issues else None
    result = b03(**counts, cohort_verified=True) if counts is not None else b03(None,None,None)
    return {**result, 'theme_id': section.get('theme_id'), 'trade_date':trade_date,
            'counts': counts, 'groups': groups, 'selection_audit': audit, 'issues': issues,
            'composition_verified': not issues,
            'evidence_scope': 'SYNTHETIC' if synthetic else 'SUPPLIED_LOCAL_EVIDENCE_CONTRACT'}


def derive_c02(section: dict, candidate: str, prior: str, synthetic: bool) -> dict:
    rows, audit, issues = member_rows(section, candidate, date_required=prior,
                                     synthetic=synthetic, exclude_candidate=False)
    parsed = []
    for row in rows:
        try:
            if count(row.get('board_count'), 'board_count') != 1 or row.get('close_limit_up') is not True:
                raise ValueError('not a prior-day closing first board')
            stamp = row.get('first_seal_time')
            if not isinstance(stamp, str):
                raise ValueError('first seal missing')
            clock = time.fromisoformat(stamp)
            # Reuse the allowed session clock contract to reject impossible times.
            remaining_minutes(stamp)
            parsed.append((clock, row))
        except (ValueError, TypeError) as exc:
            issues.append(f'{row.get("code")}:RANK_INPUT_INVALID:{exc}')
    selected = [p for p in parsed if p[1]['code'] == candidate]
    n = len(parsed)
    if len(selected) != 1:
        issues.append('CANDIDATE_NOT_IN_COMPLETE_PRIOR_FIRST_BOARD_SET')
    rank = None
    if n < 2:
        issues.append('NOT_COMPARABLE_SINGLETON')
    if not issues:
        target = selected[0][0]
        less = sum(p[0] < target for p in parsed)
        tied = sum(p[0] == target for p in parsed)
        rank = less + (tied + 1)/2
    return {'n':n if not issues else None, 'rank':rank, 'members':rows,
            'selection_audit':audit, 'issues':issues,
            'rule':'previous-day all eligible first boards; later failures retained; average tie ranks'}


def score_document(obj: dict, *, input_dir: Path, evidence_root: Path,
                   rules: dict) -> dict:
    if obj.get('schema') != SCHEMA:
        raise ValueError('INPUT_SCHEMA_MISMATCH')
    kind = obj.get('input_type')
    if kind not in INPUT_TYPES:
        raise ValueError('INPUT_TYPE_MUST_BE_EXPLICIT')
    synthetic = kind == 'SYNTHETIC'
    if rules.get('enabled') is not False or rules.get('approval_status') != 'PENDING_USER_REVIEW':
        raise ValueError('PRODUCTION_ENABLE_NOT_SUPPORTED')
    if {x['rule_id']:x['proposed_weight'] for x in rules['items']} != WEIGHTS:
        raise ValueError('RULE_WEIGHTS_DIFFER_FROM_FROZEN_REFERENCE')
    candidate = deepcopy(obj.get('candidate', {}))
    code = candidate.get('code')
    if not isinstance(code, str) or not CODE.fullmatch(code):
        raise ValueError('SIX_DIGIT_CANDIDATE_CODE_REQUIRED')
    obs = deepcopy(obj.get('observation', {}))
    global_issues = observation_issues(obj, synthetic)
    specs = {x['rule_id']:x for x in rules['items']}
    scores, trace, known_inputs = {}, {}, {}
    b03_detail = c02_detail = None
    item_inputs = obj.get('item_inputs', {})
    for key in WEIGHTS:
        section = deepcopy(item_inputs.get(key, {}))
        values = deepcopy(section.get('values', {}))
        dates = ([obs.get('previous_trade_date')] if key=='C02' else
                 [obs.get('trade_date'),obs.get('previous_trade_date')] if key=='B02' else
                 [obs.get('trade_date')])
        issues = [issue for issue in global_issues
                  if not (key == 'C02' and issue in ['SOURCE_DATE_VERIFIED_MISSING','CLOSING_VERIFIED_MISSING'])]
        # C02 uses a verified T-1 cohort. Missing today's close must not erase
        # independently evidenced prior-day facts; the complete T score remains blocked.
        issues += review_issues(section, obs, synthetic, input_dir, evidence_root, dates)
        if not isinstance(values, dict):
            values = {}; issues.append('VALUES_NOT_OBJECT')
        if key == 'B03':
            b03_detail = derive_b03(section,code,obs.get('trade_date'),synthetic)
            issues += b03_detail['issues']
            values = b03_detail['counts'] or {}
        elif key == 'C02':
            c02_detail = derive_c02(section,code,obs.get('previous_trade_date'),synthetic)
            issues += c02_detail['issues']
            values = {k:c02_detail[k] for k in ['n','rank']}
        elif key == 'D01' and 'last_seal_time' in section:
            try:
                derived = remaining_minutes(section['last_seal_time'])
                if values.get('remaining_session_minutes') not in (None,derived):
                    issues.append('D01_RAW_AND_DERIVED_CONFLICT')
                values['remaining_session_minutes'] = derived
            except (ValueError, TypeError) as exc:
                issues.append(str(exc))
        if key in ['A02','A03','B01']:
            frac_key = {'A02':'p23','A03':'fail_high','B01':'breadth'}[key]
            basis = section.get('count_basis')
            if isinstance(basis, dict):
                try:
                    numerator=count(basis.get('numerator'),'numerator')
                    denominator=count(basis.get('denominator'),'denominator')
                    if denominator == 0 or numerator > denominator:
                        raise ValueError('invalid/zero effective denominator')
                    fraction=number(values.get(frac_key),frac_key,0,1)
                    if not math.isclose(fraction,numerator/denominator,rel_tol=1e-12,abs_tol=1e-12):
                        raise ValueError('fraction differs from X/N')
                except (ValueError,TypeError,OverflowError) as exc:
                    issues.append('COUNT_BASIS_INVALID:' + str(exc))
            elif not synthetic:
                issues.append('NUMERATOR_DENOMINATOR_REQUIRED')
        if key == 'A01' and not synthetic and section.get('source_mode') not in ['883900_NATIVE','LOCAL_APPROVED_EQUAL_WEIGHT']:
            issues.append('A01_APPROVED_SOURCE_MODE_UNSPECIFIED')
        units = section.get('units', {})
        if units != UNITS[key]:
            issues.append('CANONICAL_UNITS_MISMATCH_OR_MISSING')
        for f in UNITS[key]:
            if values.get(f) is None:
                issues.append('INPUT_MISSING:' + f)
        if not synthetic and key not in ['B03','C02']:
            # Explicit source for each canonical value (including derived aggregate files).
            for f,v in values.items():
                ref = section.get('value_refs', {}).get(f)
                if not ref:
                    issues.append('VALUE_REF_MISSING:' + f); continue
                try:
                    if not same_value(read_ref(ref,input_dir,evidence_root), v):
                        issues.append('VALUE_DIFFERS_FROM_REFERENCE:' + f)
                except (ValueError,KeyError,TypeError,OSError,IndexError) as exc:
                    issues.append('VALUE_REF_INVALID:' + f + ':' + str(exc))
        if not synthetic and key in ['B03','C02']:
            try:
                if json_bytes(read_ref(section.get('members_ref',{}),input_dir,evidence_root)) != json_bytes(section.get('members')):
                    issues.append('MEMBER_LIST_DIFFERS_FROM_REFERENCE')
            except (ValueError,KeyError,TypeError,OSError,IndexError) as exc:
                issues.append('MEMBER_LIST_REF_MISSING_OR_INVALID:' + str(exc))
        result = None
        if not issues:
            try:
                result = calculate_reference(values,verified_ids={key})
                if result['item_scores'][key] is None:
                    issues.append(result['missing_or_invalid'][key])
            except (OverflowError, ValueError, TypeError, KeyError) as exc:
                issues.append('ARITHMETIC_INPUT_ERROR:' + str(exc))
        score = result['item_scores'][key] if result is not None and not issues else None
        scores[key] = score
        if score is not None:
            known_inputs.update(values)
        trace[key] = {'name':specs[key]['name'], 'proposed_weight':WEIGHTS[key],
                      'rule_status':'PENDING_USER_REVIEW', 'input_values':values,
                      'input_units':units, 'expected_units':UNITS[key],
                      'score_unit':'proposal_points', 'count_basis':section.get('count_basis'),
                      'source_mode':section.get('source_mode'), 'source_review':section.get('review',{}),
                      'source_value_refs':section.get('value_refs',{}),
                      'formula':specs[key]['formula'], 'rationale':specs[key]['rationale'],
                      'score':score, 'data_status':'INPUT_PENDING' if issues else
                               'SYNTHETIC_ARITHMETIC' if synthetic else 'SUPPLIED_EVIDENCE_PASSED_LOCAL_CHECKS',
                      'issues':list(dict.fromkeys(issues))}
    known = [v for v in scores.values() if v is not None]
    completed = len(known) == len(WEIGHTS)
    if candidate.get('eligibility_status') not in ['ELIGIBLE_RESEARCH', 'SYNTHETIC_ELIGIBLE']:
        global_issues.append('CANDIDATE_ELIGIBILITY_' + str(candidate.get('eligibility_status','UNKNOWN')))
    # No claim that a local evidence-attestation check is independent market validation.
    eligible = candidate.get('eligibility_status') == ('SYNTHETIC_ELIGIBLE' if synthetic else 'ELIGIBLE_RESEARCH')
    total = sum(known) if completed and eligible and not global_issues else None
    return {
      'schema':'5535_S02_R1_RESEARCH_RESULT_V1', 'version':'S02_WEIGHT_PROPOSAL_R1',
      'implementation_version':'S02_R1_INPUT_ADAPTER_FIX1',
      'input_type':kind, 'candidate':candidate, 'observation':obs,
      'enabled':False, 'approval_status':'PENDING_USER_REVIEW', 'strategy_status':'NOT_ENABLED',
      'item_scores':scores, 'items':trace, 'b03_composition':b03_detail,
      'c02_ranking':c02_detail,
      'known_subtotal':sum(known) if known else None, 'known_scored_item_count':len(known),
      'research_score_proposal':total,
      'modules':{g:sum(scores[k] for k in scores if k.startswith(g))
                   if all(scores[k] is not None for k in scores if k.startswith(g)) else None
                   for g in 'ABCD'},
      'observations_only':{k:{'score':None,'role':'OBSERVATION_ONLY',
                           'details':deepcopy(obj.get('observations_only',{}).get(k))}
                           for k in ['C01','C03','D04']},
      'mainline_five_steps':deepcopy(obj.get('mainline_five_steps',{})),
      'issues':list(dict.fromkeys(global_issues)),
      'formula_demonstrations_not_scores':deepcopy(obj.get('formula_demonstrations_not_scores',[])),
      'final_score':None,'grade':None,'permission':None,
      'note':'Independent proposal only. No production writes. Source hashes prove local file identity, not market truth. No future label input, no normalization, no probabilities, no approval inferred.'}


def render_explanation(result: dict) -> str:
    c=result['candidate']; obs=result['observation']
    lines=[f'# 候选研究解释｜{c.get("name","")}（{c["code"]}）', '',
           f'输入类型：**{result["input_type"]}**。规则是待审提案，正式策略未启用。',
           f'观察日声明：{obs.get("trade_date")}；采样声明：{obs.get("captured_at")}。',
           f'源日期核实：{obs.get("source_date_verified")}；收盘核实：{obs.get("closing_verified")}。',
           f'候选资格：**{c.get("eligibility_status","UNKNOWN")}**；依据：{c.get("eligibility_reason","未提供")}。',
           '', '## 分项证据与得分',
           '|项|预算|输入/单位|得分|数据状态及缺口|','|---|---:|---|---:|---|']
    for k,v in result['items'].items():
        values=json.dumps(v['input_values'],ensure_ascii=False)
        scored='null' if v['score'] is None else f'{v["score"]:.4f}'
        issues='；'.join(v['issues']) or v['data_status']
        lines.append(f'|{k} {v["name"]}|{v["proposed_weight"]}|{values}|{scored}|{issues}|')
    lines += ['',f'已验证输入的分项数：{result["known_scored_item_count"]}/12。',
              f'有效分项小计：{result["known_subtotal"]}；完整研究分：**{result["research_score_proposal"]}**。',
              '没有可用分项时小计为null，不是0分；缺项不归一化，不生成完整排名。',
              '', '## B03逐股组成']
    detail=result['b03_composition']
    if detail and detail.get('counts') is not None and result['item_scores']['B03'] is not None:
        for key,rows in detail['groups'].items():
            lines.append(f'- {key}：'+(', '.join(r['code'] for r in rows) or '输入名单中0只'))
        lines.append(f'分档：{detail["parts"]}；B03={result["item_scores"]["B03"]}。')
    else:
        lines.append('题材或成员/日期/收盘证据未齐，人数与得分不冒填0。部分行仅为待核参考，不能合并静态概念凑数。')
    lines += ['', '## 三项观察与主线五步',
              'C01、C03、D04只作说明，无隐性加扣分，也不是0分项。',
              '主线第五步要先确定题材异动日t0；t0的下一交易日已发生且不晚于T时可提供历史反馈证据。T之后的信息只能用于后验验证；本例不自动选定t0。',
              '', '## 结论',
              '保留已知记录与未知原因。完整输入未通过时不输出完整评分；规则可供独立研究复算，不代表评级、仓位或交易放行。']
    return '\n'.join(lines)+'\n'
