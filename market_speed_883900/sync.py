"""One index-range request, then short DB commit. No per-stock history loop."""
from __future__ import annotations
import json,os,subprocess,sys,time,uuid
from pathlib import Path
from .common import *
from . import storage
from .money_view import make_view

def fetch_bounded(cfg,project,timeout=25):
 env=os.environ.copy();env['PYTHONPATH']=str(Path(__file__).resolve().parents[1])+os.pathsep+str(project)+os.pathsep+env.get('PYTHONPATH','')
 try:
  p=subprocess.run([sys.executable,'-B','-X','utf8','-m','market_speed_883900.index_source'],input=dumps(cfg),capture_output=True,text=True,encoding='utf8',env=env,timeout=timeout)
 except subprocess.TimeoutExpired:return {'ok':False,'error':'883900本次请求超时上限，子进程已回收；没有生成假值'}
 try:return json.loads(p.stdout.strip().splitlines()[-1])
 except Exception:return {'ok':False,'error':'来源进程没有合法结构化结果','stderr':p.stderr[-500:]}

def sync_index(project,start='20260701',end=None,mode='history',allow_during_update=False,adapter=None,fetcher=fetch_bounded):
 db=database(project);ident=uuid.uuid4().hex;started=time.time();owner=ident
 if update_running(db) and not allow_during_update:return {'status':'YIELD_TO_DAILY_UPDATE','writes':False}
 if not storage.lease(db,'883900_fetch',owner,seconds=45):return {'status':'ALREADY_RUNNING','writes':False}
 try:
  calendar=read_calendar(project,db);finished=latest_finished(calendar)
  if not finished:return {'status':'NO_VERIFIED_FINISHED_CALENDAR','writes':False}
  end=day(end) or finished
  if end>finished:return {'status':'REQUEST_NOT_FINALIZED','writes':False,'last_completed':finished}
  index=next((i for i,d in enumerate(calendar) if d>=start),None)
  if index is None:raise ValueError('日历没有目标起点')
  # At least five earlier sessions, not calendar days, for July 1's daily pct + MA5.
  pre=calendar[max(0,index-5)]
  if mode=='latest':pre=calendar[max(0,calendar.index(end)-7)]
  existing=storage.daily_rows(db)
  if mode=='history':
   view=make_view(calendar,existing,end,start)
   if view['status']=='READY':
    storage.set_active(db,True);return {'status':'ALREADY_COMPLETE','coverage':view['history_coverage'],'requests':0,'activated':True}
  res=fetcher({'start':pre,'end':end,'calendar':calendar,'mode':mode,'adapter':adapter},project,25)
  if not res.get('ok'):
   detail={'status':'SOURCE_UNAVAILABLE','detail':res,'writes_daily':False,'kept_existing_view':True}
   storage.save_run(db,ident,'883900_sync',started,'SOURCE_UNAVAILABLE',detail);return detail
  bundle=res['bundle']
  if update_running(db) and not allow_during_update:return {'status':'YIELD_BEFORE_COMMIT','writes_daily':False,'raw_received_days':len(bundle['daily'])}
  saved=storage.save_index(db,bundle,activate=False)
  view=make_view(calendar,storage.daily_rows(db),end,start)
  # First activation only after full requested history+warmup is available.
  # A failed source may not wipe the previously usable local series.
  if view['status']=='READY':storage.set_active(db,True)
  out={'status':'COMPLETE' if view['status']=='READY' else 'PARTIAL_SOURCE_COVERAGE','range':[start,end],'coverage':view['history_coverage'],'missing_daily':[r['date'] for r in view['history'] if r['earning_effect'] is None],'missing_mean5':[r['date'] for r in view['history'] if r['fund_cycle'] is None],'activated':storage.active(db),'new_days':saved['new_or_revised_days'],'source':SERIES,'elapsed_seconds':round(time.time()-started,3),'requests_detail':bundle.get('attempts'),'no_local_mean_mixing':True}
  storage.save_run(db,ident,'883900_sync',started,out['status'],out);return out
 except Exception as exc:
  out={'status':'ERROR','error_type':type(exc).__name__,'error':str(exc),'elapsed_seconds':time.time()-started}
  try:storage.save_run(db,ident,'883900_sync',started,'ERROR',out)
  except Exception:pass
  return out
 finally:storage.release(db,'883900_fetch',owner)

# BEGIN M8839_TAIL_FRESHNESS_R1
from .freshness_r1 import sync_index as sync_index
# END M8839_TAIL_FRESHNESS_R1
