"""Index-only five-day view; old local cohort mean is retained, never mixed."""
from __future__ import annotations
import copy
from .common import *
from . import storage

def make_view(calendar,records,end,start='20260701'):
 # stage thresholds for fund-cycle % (user-confirmed: <=-2 / (-2,2] / (2,5] / (5,8] / (8,13] / (13,17] / >17)
 def stage_sum(v):
  if v is None:return None
  for edge,label in [(-2,'深度反击'),(2,'启动进攻'),(5,'均衡参与'),(8,'动能减弱'),(13,'防御减仓'),(17,'退潮警戒')]:
   if v<=edge:return label
  return '脉冲尾声'
 cal=sorted(set(d for d in calendar if day(d)==d and d<=end));rows=[]
 # If end date has a record but is missing from calendar (e.g. today not yet in P50 calendar), append it.
 if end not in cal and end in records:
  cal.append(end);cal.sort()
 for i,d in enumerate(cal):
  if d<start:continue
  w=cal[max(0,i-4):i+1];missing=[x for x in w if x not in records];rec=records.get(d)
  value=number(rec.get('pct')) if rec else None
  vals=[{'date':x,'value':number(records[x].get('pct')) if x in records else None,'status':'VALID' if x in records else 'DATA_PENDING','source':SERIES,'revision_id':records.get(x,{}).get('id')} for x in w]
  # 资金周期：T-4 前收盘 -> T 收盘，累计包含 T-4 当日涨跌。
  rec0=records.get(w[0]);recN=records.get(w[-1]) if len(w)==5 else None
  cl0=number(rec0.get('preclose_value')) if rec0 else None
  clN=number(recN.get('close_value')) if recN else None
  total5=round((clN/cl0-1)*100,2) if len(w)==5 and not missing and cl0 and clN and cl0>0 else None
  rows.append({'date':d,'earning_effect':value,'fund_cycle':total5,'fund_cycle_exact':total5,'daily':{'date':d,'value':value,'status':'VALID' if value is not None else 'DATA_PENDING','source':SERIES,'source_scope':'THS_883900_INDEX_NOT_LOCAL_COHORT','unit':'%','revision_id':rec.get('id') if rec else None},'status':'VALID' if total5 is not None else 'DATA_PENDING','window_dates':w,'window_values':vals,'missing_dates':missing,'warmup_missing':len(w)<5,'window_size':5,'unit':'%','stage':stage_sum(total5) if total5 is not None else None,'formal_strategy':'NOT_ENABLED','action_authorized':False})
 current=next((r for r in reversed(rows) if r['date']==end),{'date':end,'status':'DATA_PENDING','earning_effect':None,'fund_cycle':None,'daily':{'status':'DATA_PENDING','value':None,'source':SERIES}})
 return {'date':end,'current':current,'history':rows,'data_source':'SQLITE_ONLY','database_only':True,'source':SERIES,'source_label':'同花顺883900昨日涨停指数日涨幅','display_window':{'start':start,'end':end},'status':'READY' if rows and all(r['status']=='VALID' for r in rows) else 'PARTIAL','history_coverage':{'display_rows':len(rows),'earning_effect_valid':sum(r['earning_effect'] is not None for r in rows),'fund_cycle_valid':sum(r['fund_cycle'] is not None for r in rows)},'formal_strategy':'NOT_ENABLED','action_authorized':False,'source_policy':'指数连续序列；不与本地成员等权均值拼接'}

def overlay(base,calendar,db):
 if not storage.active(db):return base
 out=copy.deepcopy(base);view=make_view(calendar,storage.daily_rows(db),base['date'])
 out['money_effect_source_comparison']={'local_mean_available':bool(base.get('five_day_money_effect')),'local_mean_diagnostic':'/api/dashboard?date='+base['date']+'&source=local','note':'原研究/历史记录保留；本次只切换赚钱效应展示源，不自动回写研究A01'}
 out['five_day_money_effect']=view;out['five_day_fund_cycle']=view['current'];return out
