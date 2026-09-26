"""All constructed fixtures here are synthetic, including fault injection of review flags."""
from __future__ import annotations
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'research'))
from research_adapter import (score_document, derive_b03, derive_c02, remaining_minutes,
                              parse_json, read_ref, render_explanation)
from reference_calculator import calculate_reference,WEIGHTS
RULES=json.loads((ROOT/'research/02_权重与分档提案_未启用.json').read_text(encoding='utf-8'))
BASE=json.loads((ROOT/'inputs/synthetic_72_25.json').read_text(encoding='utf-8'))
ACTUAL=json.loads((ROOT/'inputs/nanjing_port_intraday.json').read_text(encoding='utf-8'))

def run_doc(doc,base=None,root=None):
    return score_document(doc,input_dir=base or ROOT/'inputs',evidence_root=root or ROOT,rules=RULES)

def ladder(a,b,c):
    section={'theme_id':'SYNTHETIC_THEME','theme_confirmed':True,'membership_complete':True,'members':[]}
    for i,height in enumerate([1]*a+[2]*b+[3]*c):
        section['members'].append({'code':f'93{i:04}', 'trade_date':'2026-09-10','theme_id':'SYNTHETIC_THEME','selection':'INCLUDED','close_limit_up':True,'board_count':height})
    return section


def reviewed_fixture(path):
    """Synthetic local attestation fixture, never represented as actual market evidence."""
    d=deepcopy(BASE)
    d['input_type']='CLOSING_EVIDENCE_SUPPLIED'
    d['candidate']['eligibility_status']='ELIGIBLE_RESEARCH'
    d['candidate']['name']='SYNTHETIC_EVIDENCE_CONTRACT_TEST'
    d['observation'].update(source_date_verified=True,closing_verified=True,
        previous_trade_date_verified=True,decision_asof='2026-09-10T16:00:00+08:00')
    for sec in d['item_inputs'].values():
        for row in sec.get('members',[]): row['data_status']='VERIFIED'
    source=path/'synthetic_contract.json'
    source.write_text(json.dumps(d['item_inputs'],ensure_ascii=False),encoding='utf-8')
    digest=sha256(source.read_bytes()).hexdigest()
    def ref(pointer): return {'file':source.name,'sha256':digest,'pointer':pointer}
    for k,sec in d['item_inputs'].items():
        dates=['2026-09-09'] if k=='C02' else ['2026-09-10','2026-09-09'] if k=='B02' else ['2026-09-10']
        sec['review']={'status':'VERIFIED','source_dates':dates,'units_verified':True,
                      'scope_verified':True,'closing_verified':True,'available_at':'2026-09-10T15:30:00+08:00',
                      'evidence_refs':[ref('/'+k)]}
        sec['value_refs']={v:ref('/'+k+'/values/'+v) for v in sec['values']}
        if k in ['B03','C02']:sec['members_ref']=ref('/'+k+'/members')
    return d


class AdapterTests(unittest.TestCase):
 def test_01_synthetic_72_25(self):
    r=run_doc(BASE);self.assertAlmostEqual(r['research_score_proposal'],72.25)
    self.assertEqual(r['modules'],{'A':20.75,'B':31,'C':6.4,'D':14.1})
 def test_02_actual_intraday_no_scored_subtotal(self):
    r=run_doc(ACTUAL)
    self.assertIsNone(r['known_subtotal']);self.assertIsNone(r['research_score_proposal'])
    self.assertEqual(r['known_scored_item_count'],0)
    self.assertTrue(all(x is None for x in r['item_scores'].values()))
 def test_03_all_12_rows_and_3_observers(self):
    r=run_doc(ACTUAL);self.assertEqual(set(r['items']),set(WEIGHTS))
    self.assertEqual(set(r['observations_only']),{'C01','C03','D04'})
    self.assertTrue(all(x['score'] is None for x in r['observations_only'].values()))
 def test_04_no_promotion_to_formal(self):
    for d in [BASE,ACTUAL]:
        r=run_doc(d);self.assertFalse(r['enabled']);self.assertEqual(r['approval_status'],'PENDING_USER_REVIEW')
        self.assertEqual(r['strategy_status'],'NOT_ENABLED')
        self.assertTrue(all(r[k] is None for k in ['final_score','grade','permission']))
 def test_05_changed_input_affects_calculation(self):
    d=deepcopy(BASE);d['item_inputs']['D02']['values']['open_break_count']=0
    r=run_doc(d);self.assertAlmostEqual(r['research_score_proposal'],75.25)
 def test_06_partial_not_normalized(self):
    d=deepcopy(BASE);d['item_inputs']['D03']['values']['seal_amount']=None
    r=run_doc(d);self.assertIsNone(r['research_score_proposal'])
    self.assertAlmostEqual(r['known_subtotal'],68.65)
 def test_07_bool_nonfinite_invalid_per_item(self):
    for value in [True,False,float('nan'),float('inf'),'30',30]:
        d=deepcopy(BASE);d['item_inputs']['A02']['values']['p23']=value
        self.assertIsNone(run_doc(d)['item_scores']['A02'])
 def test_08_unit_mismatch_not_guessed(self):
    d=deepcopy(BASE);d['item_inputs']['A02']['units']['p23']='percent'
    self.assertIsNone(run_doc(d)['item_scores']['A02'])
 def test_09_nonstandard_json_rejected(self):
    for v in ['NaN','Infinity','-Infinity']:
        with self.assertRaises(ValueError):parse_json(('{"x":'+v+'}').encode())
 def test_10_b03_expected_ladders(self):
    for a,b,c,total in [(1,0,1,7),(5,0,3,13),(5,3,3,18),(3,1,1,12),(0,0,0,0)]:
        r=derive_b03(ladder(a,b,c),'999999','2026-09-10',True)
        self.assertEqual(r['score'],total);self.assertEqual(r['counts'],dict(n1=a,n2=b,n3plus=c))
 def test_11_b03_candidate_removed(self):
    r=run_doc(BASE)['b03_composition']
    self.assertEqual(r['counts'],{'n1':3,'n2':1,'n3plus':1})
    self.assertTrue(any(x['action']=='REMOVE_CANDIDATE_SELF' for x in r['selection_audit']))
 def test_12_duplicate_identical_dedup(self):
    b=ladder(1,0,1);b['members'].append(deepcopy(b['members'][0]))
    r=derive_b03(b,'999999','2026-09-10',True);self.assertEqual(r['score'],7)
 def test_13_duplicate_conflict_blocked(self):
    b=ladder(1,0,1);row=deepcopy(b['members'][0]);row['board_count']=2;b['members'].append(row)
    self.assertIsNone(derive_b03(b,'999999','2026-09-10',True)['score'])
 def test_14_mixed_theme_or_date_blocked(self):
    for f,v in [('theme_id','OTHER'),('trade_date','2026-09-11')]:
        b=ladder(1,0,1);b['members'][0][f]=v
        self.assertIsNone(derive_b03(b,'999999','2026-09-10',True)['score'])
 def test_15_unknown_cohort_not_zero(self):
    b=ladder(0,0,0);b['membership_complete']=False
    self.assertIsNone(derive_b03(b,'999999','2026-09-10',True)['score'])
 def test_16_unknown_member_not_silently_deleted(self):
    b=ladder(1,0,1);b['members'][0]['board_count']=None
    self.assertIsNone(derive_b03(b,'999999','2026-09-10',True)['score'])
 def test_17_approved_missing_exclusion_separate(self):
    b=ladder(2,0,1);b['members'][0].update(selection='EXCLUDED_APPROVED',exclusion_reasons=['NECESSARY_DATA_MISSING'],board_count=None)
    r=derive_b03(b,'999999','2026-09-10',True)
    self.assertEqual(r['score'],7);self.assertEqual(r['selection_audit'][0]['action'],'EXCLUDED_APPROVED')
 def test_18_candidate_trade_filter_not_market_filter(self):
    b=ladder(1,1,1);b['members'][1]['candidate_only_reason']='TWO_OPEN_LIMIT_DAYS'
    self.assertEqual(derive_b03(b,'999999','2026-09-10',True)['counts']['n2'],1)
 def test_19_nonapproved_exclusion_not_applied(self):
    b=ladder(1,0,1);b['members'][0].update(selection='EXCLUDED_APPROVED',exclusion_reasons=['TWO_OPEN_LIMIT_DAYS'])
    self.assertIsNone(derive_b03(b,'999999','2026-09-10',True)['score'])
 def test_20_c02_rank_ties(self):
    c=deepcopy(BASE['item_inputs']['C02']);c['members'][1]['first_seal_time']='09:35:00'
    r=derive_c02(c,'999999','2026-09-09',True);self.assertEqual(r['rank'],1.5)
 def test_21_c02_missing_competitor_blocks_rank(self):
    c=deepcopy(BASE['item_inputs']['C02']);c['members'][-1]['first_seal_time']=None
    self.assertIsNone(derive_c02(c,'999999','2026-09-09',True)['rank'])
 def test_22_c02_later_failure_is_retained(self):
    c=deepcopy(BASE['item_inputs']['C02']);c['members'][0]['today_promotion']=False
    r=derive_c02(c,'999999','2026-09-09',True);self.assertEqual((r['n'],r['rank']),(6,2))
 def test_23_c02_singleton(self):
    c=deepcopy(BASE['item_inputs']['C02']);c['members']=[c['members'][1]]
    self.assertIsNone(derive_c02(c,'999999','2026-09-09',True)['rank'])
 def test_24_clock(self):
    for clock,mins in [('09:25:00',240),('09:30:00',240),('10:30:00',180),('11:30:00',120),('13:00:00',120),('15:00:00',0)]:
        self.assertEqual(remaining_minutes(clock),mins)
    with self.assertRaises(ValueError):remaining_minutes('12:00:00')
 def test_25_local_attestation_distinct_from_approval(self):
    with tempfile.TemporaryDirectory() as td:
        p=Path(td);d=reviewed_fixture(p);r=run_doc(d,p,p)
        self.assertAlmostEqual(r['research_score_proposal'],72.25)
        self.assertEqual(r['approval_status'],'PENDING_USER_REVIEW')
 def test_26_future_data_rejected(self):
    with tempfile.TemporaryDirectory() as td:
        p=Path(td);d=reviewed_fixture(p);d['item_inputs']['A01']['review']['available_at']='2026-09-11T09:00:00+08:00'
        r=run_doc(d,p,p);self.assertIsNone(r['item_scores']['A01']);self.assertIsNone(r['research_score_proposal'])
 def test_27_source_value_mismatch_rejected(self):
    with tempfile.TemporaryDirectory() as td:
        p=Path(td);d=reviewed_fixture(p);d['item_inputs']['D02']['values']['open_break_count']=0
        self.assertIsNone(run_doc(d,p,p)['item_scores']['D02'])
 def test_28_hash_mismatch_rejected(self):
    with tempfile.TemporaryDirectory() as td:
        p=Path(td);d=reviewed_fixture(p);(p/'synthetic_contract.json').write_text('{}')
        self.assertIsNone(run_doc(d,p,p)['research_score_proposal'])
 def test_29_member_list_evidence_required(self):
    with tempfile.TemporaryDirectory() as td:
        p=Path(td);d=reviewed_fixture(p);d['item_inputs']['B03'].pop('members_ref')
        self.assertIsNone(run_doc(d,p,p)['item_scores']['B03'])
 def test_30_captured_not_promoted_by_plausible_values(self):
    d=deepcopy(BASE);d['input_type']='CAPTURED_UNVERIFIED'
    self.assertEqual(run_doc(d)['known_scored_item_count'],0)
 def test_31_dated_claim_not_inferred(self):
    r=run_doc(ACTUAL);self.assertFalse(r['observation']['source_date_verified'])
    self.assertEqual(r['observation']['captured_at'],'2026-09-10 11:53:40')
 def test_32_eligibility_unknown_or_excluded_no_total(self):
    for state in ['UNKNOWN','EXCLUDED']:
        d=deepcopy(BASE);d['candidate']['eligibility_status']=state
        self.assertIsNone(run_doc(d)['research_score_proposal'])
 def test_33_observers_cannot_change_score(self):
    d=deepcopy(BASE);d['observations_only']={'C01':{'fake_score':8},'C03':{'fake_score':100},'D04':{'fake_score':8}}
    self.assertEqual(run_doc(d)['research_score_proposal'],72.25)
 def test_34_report_no_false_zero_or_mainline_step_deletion(self):
    text=render_explanation(run_doc(ACTUAL))
    self.assertIn('完整研究分：**None**',text)
    self.assertIn('t0',text);self.assertNotIn('已知小计4.34',text)
 def test_35_explicit_cli_and_file_safety(self):
    with tempfile.TemporaryDirectory() as td:
        p=Path(td);inputp=p/'changed.json';d=deepcopy(BASE)
        d['item_inputs']['D02']['values']['open_break_count']=0
        inputp.write_text(json.dumps(d),encoding='utf-8')
        out=p/'result'
        cmd=[sys.executable,str(ROOT/'research/run_research.py'),'--input',str(inputp),'--output-dir',str(out)]
        process=subprocess.run(cmd,capture_output=True,text=True,timeout=15)
        self.assertEqual(process.returncode,0,process.stderr)
        actual=json.loads((out/'research_results.json').read_text(encoding='utf-8'))
        self.assertEqual(actual['research_score_proposal'],75.25)
        self.assertFalse((p/'dashboard.json').exists())
        self.assertNotEqual(subprocess.run(cmd,capture_output=True,timeout=15).returncode,0)
 def test_36_cli_missing_input_fails_without_writes(self):
    with tempfile.TemporaryDirectory() as td:
        p=Path(td);out=p/'out'
        proc=subprocess.run([sys.executable,str(ROOT/'research/run_research.py'),'--input',str(p/'missing.json'),'--output-dir',str(out)],capture_output=True,timeout=15)
        self.assertNotEqual(proc.returncode,0);self.assertFalse(out.exists())
 def test_37_evidence_path_traversal_blocked(self):
    with tempfile.TemporaryDirectory() as td:
        p=Path(td)
        with self.assertRaises(ValueError):read_ref({'file':'../outside.json','sha256':'x','pointer':''},p,p)
 def test_38_integer_overflow_is_item_error(self):
    d=deepcopy(BASE);d['item_inputs']['D03']['values']['seal_amount']=10**500
    self.assertIsNone(run_doc(d)['item_scores']['D03'])
 def test_39_scalar_b03_not_accepted_as_membership(self):
    d=deepcopy(BASE);d['item_inputs']['B03'].pop('members')
    self.assertIsNone(run_doc(d)['item_scores']['B03'])

 def test_40_fraction_must_match_effective_counts(self):
    d=deepcopy(BASE);d['item_inputs']['A02']['count_basis']={'numerator':4,'denominator':10}
    self.assertIsNone(run_doc(d)['item_scores']['A02'])
 def test_41_real_count_basis_not_omitted(self):
    with tempfile.TemporaryDirectory() as td:
        p=Path(td);d=reviewed_fixture(p);d['item_inputs']['A03'].pop('count_basis')
        self.assertIsNone(run_doc(d,p,p)['item_scores']['A03'])
 def test_42_883900_source_not_silently_switched(self):
    with tempfile.TemporaryDirectory() as td:
        p=Path(td);d=reviewed_fixture(p);d['item_inputs']['A01']['source_mode']='BK1050'
        self.assertIsNone(run_doc(d,p,p)['item_scores']['A01'])

 def test_43_prior_day_independent_score_survives_today_pending(self):
    with tempfile.TemporaryDirectory() as td:
        p=Path(td);d=reviewed_fixture(p)
        d['observation'].update(source_date_verified=False,closing_verified=False)
        r=run_doc(d,p,p)
        self.assertAlmostEqual(r['item_scores']['C02'],6.4)
        self.assertIsNone(r['research_score_proposal'])

if __name__=='__main__': unittest.main(verbosity=2)
