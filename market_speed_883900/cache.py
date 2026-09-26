"""Persistent, semantic-versioned last-good cache. Foreground NEVER rebuilds.
Fresh/stale is explicit. A prior date is never relabelled as a requested date.
No heartbeat/performance/log commit invalidates the display cache.
"""
from __future__ import annotations
import copy,gzip,json,logging,threading,time
from collections import OrderedDict
from .common import *
from . import storage
LOG=logging.getLogger('5535.semantic_cache')

class CacheEntry:
 def __init__(self,obj,token,ms,built_at=None):
  self.obj=obj;self.epoch=token;self.date=obj['date'];self.built_at=built_at or time.time();self.build_ms=ms
  self.raw=dumps(obj).encode();self.zipped=gzip.compress(self.raw,5,mtime=0)
 def served(self,state,current_epoch,error=None):
  obj=copy.deepcopy(self.obj)
  obj.setdefault('cockpit_transport',{}).update(version=VERSION,cache_state=state,cache_epoch=self.epoch,current_epoch=current_epoch,built_at=self.built_at,build_ms=self.build_ms,source='SQLITE_MATERIALIZED_PROJECTION',fresh=state=='FRESH',rebuild_error=bool(error))
  if state!='FRESH':obj['cockpit_transport']['notice']='正在生成新数据库视图，暂显示标注日期的上次完整版本；不是最新计算结果。'
  return obj

class SemanticCache:
 def __init__(self,db,loader,limit=8,start_worker=True):
  self.db=db;self.loader=loader;self.limit=limit;self.lock=threading.RLock();self.entries=OrderedDict();self.pending=set();self.building=None;self.errors={};self.event=threading.Event();self.closed=False;self.build_count=0;self.hit_count=0;self._epoch=0
  self.thread=None
  if start_worker:
   self.thread=threading.Thread(target=self._worker,name='5535-display-builder',daemon=True);self.thread.start()
 def current_epoch(self):
  try:self._epoch=storage.epoch(self.db)
  except (sqlite3.OperationalError,OSError):
   # DB temporarily busy -> explicit stale, not block foreground for seconds.
   return None
  return self._epoch
 def _disk(self,key):
  try:
   with connect(self.db,timeout=.05) as c:r=c.execute('SELECT * FROM m8839_cache WHERE cache_key=?',(VERSION+':'+key,)).fetchone()
   if r:
    obj=json.loads(bytes(r['raw']));return CacheEntry(obj,int(r['epoch']),r['build_ms'],r['built_at'])
  except (ValueError,sqlite3.Error,OSError):return None
 def queue(self,key,force=False):
  with self.lock:
   if self.building==key and not force:return
   # Retry a genuinely failed build no more than once per 10 seconds.
   if self.errors.get(key,{}).get('time',0)>time.time()-10:return
   self.pending.add(key);self.event.set()
 def get(self,date=None):
  key=date or '@latest';current=self.current_epoch()
  with self.lock:
   e=self.entries.get(key)
   if e is None:
    e=self._disk(key)
    if e:self.entries[key]=e
   if e and (not date or e.date==date) and current is not None and e.epoch==current:
    self.hit_count+=1;self.entries.move_to_end(key);return e,'FRESH',current
   self.queue(key)
   if e and (not date or e.date==date):return e,'STALE_REBUILDING' if not self.errors.get(key) else 'STALE_REBUILD_FAILED',current
   return None,'BUILDING',current
 def _worker(self):
  while not self.closed:
   self.event.wait(.5);self.event.clear()
   with self.lock:
    # Also maintain latest in advance of visits, after a relevant commit.
    old=self.entries.get('@latest')
   if old:
    cur=self.current_epoch()
    if cur is not None and old.epoch!=cur:self.queue('@latest')
   with self.lock:
    if not self.pending:continue
    key='@latest' if '@latest' in self.pending else sorted(self.pending)[0];self.pending.discard(key);self.building=key
   try:
    # Coalesce a burst of source/head commits; never hold a DB transaction here.
    time.sleep(.08);token=storage.epoch(self.db);t=time.perf_counter();obj=self.loader(None if key=='@latest' else key)
    if not isinstance(obj,dict) or not day(obj.get('date')) or (key!='@latest' and obj['date']!=key):raise ValueError('读取日期不匹配')
    e=CacheEntry(obj,token,(time.perf_counter()-t)*1000)
    with connect(self.db,True,timeout=2) as c:
     for k in {key,e.date}:
      c.execute('INSERT OR REPLACE INTO m8839_cache VALUES(?,?,?,?,?,?,?)',(VERSION+':'+k,e.epoch,e.date,e.built_at,e.build_ms,e.raw,e.zipped))
     c.commit()
    with self.lock:
     self.entries[key]=e;self.entries[e.date]=e;self.build_count+=1;self.errors.pop(key,None)
     while len(self.entries)>self.limit:self.entries.popitem(last=False)
    # An intervening commit means this snapshot is stale; never stamp it current.
    if storage.epoch(self.db)!=token:self.queue(key,force=True)
   except Exception as exc:
    LOG.exception('显示后台生成失败，保留最后可用版本')
    with self.lock:self.errors[key]={'time':time.time(),'type':type(exc).__name__,'message':str(exc)[:180]}
   finally:
    with self.lock:self.building=None
 def wait_ready(self,date=None,timeout=120):
  deadline=time.monotonic()+timeout
  while time.monotonic()<deadline:
   e,state,cur=self.get(date)
   if state=='FRESH':return e
   time.sleep(.05)
  raise TimeoutError('显示物化未就绪；日志见原Web控制台。原业务数据未清空。')
 def close(self):self.closed=True;self.event.set()
 def status(self):
  with self.lock:return {'build_count':self.build_count,'hits':self.hit_count,'pending':sorted(self.pending),'building':self.building,'errors':dict(self.errors),'cached_dates':sorted(self.entries)}
