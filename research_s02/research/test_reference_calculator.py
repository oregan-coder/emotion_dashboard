import json
import math
import unittest
from pathlib import Path
from reference_calculator import b03, calculate_reference, WEIGHTS

BASE={
 'r_pct':2.0,'p23':.30,'fail_high':.25,'U':90,'Z':30,'D':10,
 'breadth':.70,'excess_median_T':1.2,'excess_median_previous':.5,
 'n1':3,'n2':1,'n3plus':1,'n':6,'rank':2,
 'remaining_session_minutes':180,'open_break_count':1,
 'seal_amount':60_000_000,'circulating_market_cap':10_000_000_000}
ALL=set(WEIGHTS)
class ProposalTests(unittest.TestCase):
 def test_budget(self):
  self.assertEqual(sum(WEIGHTS.values()),100)
  self.assertEqual({g:sum(v for k,v in WEIGHTS.items() if k[0]==g) for g in 'ABCD'},dict(A=30,B=40,C=8,D=22))
  config=json.loads((Path(__file__).parent/'02_权重与分档提案_未启用.json').read_text())
  self.assertEqual(WEIGHTS,{r['rule_id']:r['proposed_weight'] for r in config['items']})
  self.assertFalse(config['enabled'])
 def test_expected_ladders(self):
  for counts,score in [((0,0,0),0),((1,0,1),7),((5,0,3),13),((3,1,1),12),((5,3,3),18),((5,0,0),6),((5,3,0),11),((0,3,3),8),((20,0,1),11)]:
   with self.subTest(counts=counts): self.assertEqual(b03(*counts,cohort_verified=True)['score'],score)
 def test_b03_range_reachability_and_monotonicity(self):
  seen=set()
  for a in range(9):
   for b in range(6):
    for c in range(6):
     score=b03(a,b,c,cohort_verified=True)['score'];seen.add(score)
     self.assertTrue(0<=score<=18)
     for alt in [(a+1,b,c),(a,b+1,c),(a,b,c+1)]:
      self.assertGreaterEqual(b03(*alt,cohort_verified=True)['score'],score)
  self.assertEqual(seen,set(range(19)))
 def test_b03_unknown_not_zero(self):
  self.assertIsNone(b03(3,1,1)['score'])
  self.assertIsNone(b03(3,None,1,cohort_verified=True)['score'])
 def test_invalid_counts(self):
  for val in [True,False,-1,1.5,'3',float('inf'),float('nan')]:
   with self.subTest(value=str(val)):
    with self.assertRaises(ValueError):b03(val,1,1,cohort_verified=True)
 def test_synthetic_total(self):
  r=calculate_reference(BASE,verified_ids=ALL)
  self.assertAlmostEqual(r['research_score_proposal'],72.25)
  for g,v in dict(A=20.75,B=31,C=6.4,D=14.1).items():self.assertAlmostEqual(r['modules'][g],v)
 def test_formal_outputs_never_enabled(self):
  r=calculate_reference(BASE,verified_ids=ALL)
  self.assertFalse(r['enabled']);self.assertEqual(r['strategy_status'],'NOT_ENABLED')
  for k in ['final_score','grade','permission']:self.assertIsNone(r[k])
 def test_missing_no_normalization(self):
  x=dict(BASE);x['seal_amount']=None;r=calculate_reference(x,verified_ids=ALL)
  self.assertIsNone(r['research_score_proposal']);self.assertIsNone(r['item_scores']['D03'])
  self.assertAlmostEqual(r['known_subtotal'],68.65)
 def test_no_evidence_pending(self):
  r=calculate_reference(BASE)
  self.assertIsNone(r['research_score_proposal']);self.assertTrue(all(v is None for v in r['item_scores'].values()))
 def test_singleton_and_zero_denominator(self):
  x=dict(BASE,n=1,rank=1,U=0,Z=0,D=0);r=calculate_reference(x,verified_ids=ALL)
  for k in ['C02','A04','A05']:self.assertIsNone(r['item_scores'][k])
 def test_valid_zero_invalid_bool_nonfinite(self):
  z=dict(BASE,open_break_count=0);self.assertEqual(calculate_reference(z,verified_ids=ALL)['item_scores']['D02'],6)
  for value in [True,float('nan'),float('inf'),30]:
   x=dict(BASE,p23=value);self.assertIsNone(calculate_reference(x,verified_ids=ALL)['item_scores']['A02'])
 def test_synthetic_full_arithmetic_max(self):
  x=dict(BASE,r_pct=5,p23=.5,fail_high=0,U=100,Z=0,D=0,breadth=1,n1=5,n2=3,n3plus=3,rank=1,remaining_session_minutes=240,open_break_count=0,seal_amount=100_000_000)
  self.assertAlmostEqual(calculate_reference(x,verified_ids=ALL)['research_score_proposal'],100)
  # A constructed joint mathematical input is not proof of market attainability.
if __name__=='__main__':unittest.main(verbosity=2)
