"""Fast foreground + observable background publication. Original update route preserved."""
from __future__ import annotations
import atexit,copy,gzip,json,logging,time
from pathlib import Path
from urllib.parse import parse_qsl,urlencode
from .common import *
from .cache import SemanticCache
from .money_view import overlay,make_view
from . import storage,update_accel
LOG=logging.getLogger('5535.883900.web')

def attach(app,web_file):
 from chart_recovery.cockpit_fast import FastMiddleware,accepts_gzip,make_environ,compact_dashboard
 from chart_recovery.web import capture
 from chart_recovery.repository import Repository
 if getattr(app.wsgi_app,'_m8839_attached',False):return app
 previous=app.wsgi_app
 if not isinstance(previous,FastMiddleware):raise RuntimeError('需要保留原最高板/驾驶舱加速入口；不整体覆盖原站')
 db=database(Path(web_file).parent);project=Path(web_file).resolve().parent
 # Installation owns schema changes; merely opening the Web app never creates
 # market data or silently changes an existing collection job.
 storage.epoch(db)
 class StableMiddleware(FastMiddleware):
  _m8839_attached=True
  def __init__(self):
   self.app=previous.app;self.db=db;self.project=project;self.static=previous.static;self.static_lock=previous.static_lock
   self.cache=SemanticCache(db,self._build);self.prewarm_result={'status':'ASYNC_FROM_SQLITE','foreground_rebuild':False}
   atexit.register(self.cache.close);self.cache.get(None)
  def _build(self,date):
   # Full, same-date, existing chain; height/research recovery logic unchanged.
   obj=previous._load(date)
   with Repository(db) as r:calendar=r.calendar(obj)
   result=overlay(obj,calendar,db)
   result.setdefault('cockpit_transport',{})['version']=VERSION
   
   # 性能优化：去掉 pool.tomorrow 里 research_view.factors 中的 calculation 大字段
   # 前端不需要这个详细的审计/调试信息，只需要 factor 的基本信息
   pool = result.get('pool')
   if isinstance(pool, dict):
       tomorrow = pool.get('tomorrow')
       if isinstance(tomorrow, list):
           for item in tomorrow:
               if not isinstance(item, dict):
                   continue
               rv = item.get('research_view')
               if not isinstance(rv, dict):
                   continue
               factors = rv.get('factors')
               if not isinstance(factors, list):
                   continue
               # 去掉每个 factor 里的 calculation 字段
               for factor in factors:
                   if isinstance(factor, dict) and 'calculation' in factor:
                       del factor['calculation']
   
   return result
  def _json(self,start,status,obj,env,extra=None):
   # 性能优化：去掉 pool.tomorrow 里 research_view.factors 中的 calculation 大字段
   pool = obj.get('pool') if isinstance(obj, dict) else None
   if isinstance(pool, dict):
       tomorrow = pool.get('tomorrow')
       if isinstance(tomorrow, list):
           for item in tomorrow:
               if not isinstance(item, dict):
                   continue
               rv = item.get('research_view')
               if not isinstance(rv, dict):
                   continue
               factors = rv.get('factors')
               if not isinstance(factors, list):
                   continue
               for factor in factors:
                   if isinstance(factor, dict) and 'calculation' in factor:
                       del factor['calculation']
   raw=dumps(obj).encode();z=accepts_gzip(env.get('HTTP_ACCEPT_ENCODING'));body=gzip.compress(raw,4,mtime=0) if z else raw
   hs=[('Content-Type','application/json; charset=utf-8'),('Content-Length',str(len(body))),('Cache-Control','no-store'),('Vary','Accept-Encoding'),('X-5535-Cockpit',VERSION)]+(extra or [])
   if z:hs.append(('Content-Encoding','gzip'))
   start(status,hs);return [b'' if env.get('REQUEST_METHOD')=='HEAD' else body]
  def __call__(self,env,start):
   path=env.get('PATH_INFO','');method=env.get('REQUEST_METHOD','GET');t=time.perf_counter()
   if path=='/api/cockpit' and method in ('GET','HEAD'):
    params=parse_qsl(env.get('QUERY_STRING',''),keep_blank_values=True);ds=[v for k,v in params if k=='date']
    if any(k!='date' for k,v in params) or len(ds)>1 or (ds and day(ds[0])!=ds[0]):return self._json(start,'400 Bad Request',{'error':'日期参数无效'},env)
    entry,state,current=self.cache.get(ds[0] if ds else None)
    if entry is None:return self._json(start,'503 Service Unavailable',{'code':'COLD_PROJECTION_BUILDING','error':'该日期显示快照正在后台准备；未返回空成功或其他日期。','retry_after_seconds':2},env,[('Retry-After','2')])
    return self._json(start,'200 OK',entry.served(state,current),env,[('X-5535-Cache',state),('Server-Timing',f'foreground;dur={(time.perf_counter()-t)*1000:.2f}'),('X-5535-Data-Date',entry.date)])
   if path=='/api/performance' and method in ('GET','HEAD'):
    return self._json(start,'200 OK',{'version':VERSION,'cache':self.cache.status(),'display_epoch':self.cache.current_epoch(),'index_active':storage.active(db),'original_update_hooks':getattr(self,'hooks',[]),'last_update':update_accel.summary(),'timing_definition':'新鲜完整页面到可交互<1秒；旧版本展示和新版本生成分别计时'},env)
   if path=='/api/ths883900' and method in ('GET','HEAD'):
    qs=dict(parse_qsl(env.get('QUERY_STRING','')));requested=qs.get('date');startday=qs.get('start','20260701')
    if (requested and day(requested)!=requested) or day(startday)!=startday:return self._json(start,'400 Bad Request',{'error':'日期无效'},env)
    with Repository(db) as r:
     b=r.base(requested);cal=r.calendar(b)
    end=requested or (b or {}).get('date')
    if not end:return self._json(start,'404 Not Found',{'error':'无已发布日期'},env)
    return self._json(start,'200 OK',make_view(cal,storage.daily_rows(db),end,startday),env)
   if path in ('/api/dashboard','/api/research/money-effect') and method in ('GET','HEAD') and storage.active(db):
    qs=dict(parse_qsl(env.get('QUERY_STRING','')))
    if qs.get('source')=='local':
     clean=dict(env);qs.pop('source');clean['QUERY_STRING']=urlencode(qs);return self.app(clean,start)
    requested=qs.get('date')
    if requested and day(requested)!=requested:return self._json(start,'400 Bad Request',{'error':'日期无效'},env)
    target=dict(env);target['PATH_INFO']='/api/dashboard';cap=capture(self.app,target)
    if not cap.get('status','').startswith('200'):start(cap['status'],cap['headers']);return [cap['body']]
    base=json.loads(cap['body'])
    with Repository(db) as r:cal=r.calendar(base)
    result=overlay(base,cal,db)
    return self._json(start,'200 OK',result if path=='/api/dashboard' else result['five_day_money_effect'],env)
   # Fast assets/HTML still use the existing implementation. ALL original update
   # HTTP calls are delegated; original claim/lock/status/score result survive.
   return super().__call__(env,start)
 app.wsgi_app=StableMiddleware()
 try:app.wsgi_app.hooks=update_accel.install_hooks(project,db)
 except Exception as exc:
  app.wsgi_app.hooks=[];LOG.exception('原更新加速挂载未完成，原更新入口仍保留: %s',exc)
 return app
