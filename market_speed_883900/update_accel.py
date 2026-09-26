"""Scoped acceleration of the ORIGINAL daily run, never a replacement pipeline.
Coalesces identical successful HTTP GETs within one run, caps absent/excessive
request timeouts, circuits repeated failures, and profiles the real run.
No changes to scoring, completeness checks, old inputs or public update routes.
Only requests in the original update thread (contextvar) are affected; outside
that scope the original requests method is called byte-for-byte with arguments.
"""
from __future__ import annotations
import contextvars,copy,cProfile,functools,importlib,json,logging,pstats,threading,time,uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
from pathlib import Path
from .common import *
from . import storage
LOG=logging.getLogger('5535.update_speed')
SCOPE=contextvars.ContextVar('5535_update_scope',default=None)
ALLOWED_SUFFIXES=('eastmoney.com','10jqka.com.cn','sina.com.cn','sina.cn','legulegu.com','tushare.pro','qq.com')
_last={};_lock=threading.Lock()

def _allowed(host):return any(host==s or host.endswith('.'+s) for s in ALLOWED_SUFFIXES)
def bounded_timeout(old):
 if old is None:return (3.05,8.)
 if isinstance(old,(int,float)):
  return (min(float(old),3.05),min(float(old),8.)) if old>0 else old
 if isinstance(old,(tuple,list)) and len(old)==2:
  return (min(float(old[0] or 3.05),3.05),min(float(old[1] or 8),8))
 return old
class RunScope:
 def __init__(self):self.cache={};self.failures={};self.host_block=set();self.events=[];self.cache_bytes=0
 def call(self,original,session,method,url,**kwargs):
  import requests
  u=urlsplit(str(url));host=(u.hostname or '').lower()
  if not _allowed(host) or kwargs.get('stream') or str(method).upper() not in ('GET','POST'):
   return original(session,method,url,**kwargs)
  endpoint=(host,u.path);event={'host':host,'path':u.path,'method':str(method).upper()};t=time.perf_counter()
  if host in self.host_block or self.failures.get(endpoint,0)>=2:
   self.events.append(dict(event,state='CIRCUIT_OPEN',elapsed_ms=0))
   raise requests.exceptions.ConnectionError('本轮该接口连续失败或受限，已熔断；由原流程报告缺源或切换来源')
  # Exact URL + params + request/session auth/cookies/options. No secret is logged.
  key=digest({'method':method,'url':str(url),'kwargs':repr(kwargs),'session_headers':repr(dict(session.headers)),'session_cookies':repr(session.cookies.get_dict()),'auth':repr(session.auth),'proxies':repr(session.proxies),'verify':repr(session.verify)})
  old=self.cache.get(key)
  if str(method).upper()=='GET' and old and time.monotonic()-old[0]<=2:
   self.events.append(dict(event,state='SAME_RUN_HIT',elapsed_ms=0));return copy.deepcopy(old[1])
  kwargs=dict(kwargs);kwargs['timeout']=bounded_timeout(kwargs.get('timeout'))
  try:
   response=original(session,method,url,**kwargs)
   if response.status_code in (401,403,429):self.host_block.add(host)
   if response.status_code>=500:self.failures[endpoint]=self.failures.get(endpoint,0)+1
   # Never cache HTML, challenge/error JSON, or fake empty successful responses.
   head=response.content[:500].lower();good=(response.status_code==200 and bool(response.content) and b'<html' not in head and b'captcha' not in head and b'access denied' not in head and b'"error"' not in head)
   if good and str(method).upper()=='GET' and len(response.content)<=8*1024*1024 and self.cache_bytes+len(response.content)<=32*1024*1024:
    self.cache[key]=(time.monotonic(),copy.deepcopy(response));self.cache_bytes+=len(response.content)
   self.events.append(dict(event,state='NETWORK',status=response.status_code,elapsed_ms=round((time.perf_counter()-t)*1000,2)));return response
  except requests.exceptions.RequestException as exc:
   self.failures[endpoint]=self.failures.get(endpoint,0)+1
   self.events.append(dict(event,state='FAILED',error_type=type(exc).__name__,elapsed_ms=round((time.perf_counter()-t)*1000,2)));raise

def install_requests_scope():
 import requests
 original=requests.sessions.Session.request
 if getattr(original,'_m8839_wrapped',False):return
 @functools.wraps(original)
 def request(self,method,url,**kwargs):
  current=SCOPE.get()
  return current.call(original,self,method,url,**kwargs) if current else original(self,method,url,**kwargs)
 request._m8839_wrapped=True;requests.sessions.Session.request=request

def summary():
 with _lock:return copy.deepcopy(_last)

def wrap_run(original,project,db,with_index=True):
 @functools.wraps(original)
 def run(*args,**kwargs):
  if SCOPE.get() is not None:return original(*args,**kwargs)
  from .sync import sync_index
  scope=RunScope();tok=SCOPE.set(scope);ident=uuid.uuid4().hex;started=time.time();prof=cProfile.Profile();pool=None;future=None;error=None
  with _lock:_last.update(status='RUNNING',started_at=started,run_id=ident)
  try:
   # Independent 883900 fetch, not another whole-market update. One bounded
   # subprocess in parallel with the original pipeline; no per-stock backfill.
   if with_index:
    pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='883900-daily')
    future=pool.submit(sync_index,project,mode='latest',allow_during_update=True)
   prof.enable();result=original(*args,**kwargs);prof.disable();return result
  except BaseException as exc:prof.disable();error=type(exc).__name__;raise
  finally:
   index_result=None
   try:
    if future:
     index_result=future.result(timeout=75)
     # The original updater may extend the verified calendar after the parallel
     # fetch began. One catch-up only on a newly committed session; never loop or
     # retry a failed/unavailable source in the same run.
     if index_result.get('status') in ('COMPLETE','PARTIAL_SOURCE_COVERAGE'):
      old_end=(index_result.get('range') or [None,None])[-1]
      new_end=latest_finished(read_calendar(project,db))
      if old_end and new_end and new_end>old_end:
       previous=index_result;index_result=sync_index(project,mode='latest',allow_during_update=True)
       index_result['calendar_catchup_from']=old_end
       index_result['initial_parallel_status']=previous['status']
   except Exception as exc:index_result={'status':'INDEX_REFRESH_FAILED','error_type':type(exc).__name__}
   if pool:pool.shutdown(wait=False,cancel_futures=True)
   SCOPE.reset(tok)
   stats=pstats.Stats(prof);tops=[]
   for (filename,line,name),(cc,nc,tt,ct,callers) in sorted(stats.stats.items(),key=lambda item:item[1][3],reverse=True)[:30]:
    tops.append({'file':Path(filename).name,'line':line,'function':name,'calls':nc,'self_s':round(tt,3),'cumulative_s':round(ct,3)})
   detail={'status':'FAILED' if error else 'ORIGINAL_RUN_RETURNED','error_type':error,'run_id':ident,'wall_seconds':round(time.time()-started,3),'network_events':scope.events,'same_run_hits':sum(e['state']=='SAME_RUN_HIT' for e in scope.events),'top_functions':tops,'index_refresh':index_result,'scope':'原更新线程；SDK自己创建的线程/非requests传输未改','original_result_unmodified':True,'not_a_fixed_time_success':True}
   with _lock:_last.clear();_last.update(detail)
   try:storage.save_run(db,ident,'daily_update',started,detail['status'],detail);storage.invalidate(db)
   except Exception:LOG.exception('性能记录失败，不改原更新结果')
 run._m8839_wrapped=True;return run

def install_hooks(project,db):
 """Patch exact function identities, including already-imported host aliases."""
 import sys
 install_requests_scope();installed=[];root=Path(project).resolve()
 targets=[]
 # Legacy run_update contains fetch_dashboard_data BEFORE run_pipeline. Wrapping
 # only run_pipeline misses its main network time. Use the already-loaded Web
 # module, including __main__, never import web_app and create a second app.
 for name,module in list(sys.modules.items()):
  f=getattr(module,'__file__',None)
  try:is_web=bool(f) and Path(f).resolve()==root/'web_app.py'
  except (TypeError,ValueError):is_web=False
  if is_web and callable(getattr(module,'run_update',None)):
   targets.append((name,module,'run_update'))
 for name,func in [('automation5535.pipeline','run'),('start','run_pipeline')]:
  try:module=importlib.import_module(name);getattr(module,func)
  except (ImportError,AttributeError):continue
  targets.append((name,module,func))
 for name,module,func in targets:
  original=getattr(module,func)
  if getattr(original,'_m8839_wrapped',False):continue
  wrapped=wrap_run(original,root,db,with_index=True);setattr(module,func,wrapped);installed.append(name+'.'+func)
  for m in list(sys.modules.values()):
   f=getattr(m,'__file__',None)
   if not f:continue
   try:inside=Path(f).resolve().is_relative_to(root)
   except (ValueError,TypeError):inside=False
   if inside:
    for k,v in list(vars(m).items()):
     if v is original:setattr(m,k,wrapped)
 return installed
