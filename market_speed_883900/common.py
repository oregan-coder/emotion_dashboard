"""Shared utilities. No network or writes on import."""
from __future__ import annotations
import datetime as dt, hashlib, json, math, re, sqlite3, time
from pathlib import Path
from zoneinfo import ZoneInfo
VERSION='5535_THS883900_SPEED_V1'
CODE='883900'
NAME='昨日涨停'
SERIES='THS_883900_INDEX_DAILY_PCT'
def dumps(obj):return json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(obj):return hashlib.sha256((obj if isinstance(obj,bytes) else dumps(obj).encode())).hexdigest()
def day(x):
 s=str(x or '').strip().replace('-','')
 if not re.fullmatch(r'\d{8}',s):return None
 try:dt.datetime.strptime(s,'%Y%m%d');return s
 except ValueError:return None
def number(x):
 if isinstance(x,bool) or x is None:return None
 try:v=float(str(x).replace(',','').rstrip('%'));return v if math.isfinite(v) else None
 except (ValueError,TypeError):return None
def now_iso():return dt.datetime.now(dt.timezone.utc).isoformat()
def china_now():
 try:return dt.datetime.now(ZoneInfo('Asia/Shanghai'))
 except Exception:return dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
def latest_finished(calendar,now=None):
 now=now or china_now();date=now.strftime('%Y%m%d')
 return max((d for d in calendar if d<date or (d==date and (now.hour,now.minute)>=(15,30))),default=None)
def database(project):
 p=Path(project).resolve()
 for name in ('5535_automation.json','p50_config.json'):
  cfg=p/name
  if cfg.is_file():
   value=json.loads(cfg.read_text('utf-8-sig')).get('database')
   if value:
    f=Path(value).expanduser();f=f if f.is_absolute() else p/f
    if not f.is_file():raise FileNotFoundError('原数据库不存在，拒绝创建空库: '+str(f))
    return f.resolve()
 raise FileNotFoundError('原配置没有database字段')
def connect(db,write=False,timeout=1):
 p=Path(db).resolve()
 if not p.is_file():raise FileNotFoundError(p)
 c=sqlite3.connect(p.as_uri()+('?mode=rw' if write else '?mode=ro'),uri=True,timeout=timeout)
 c.row_factory=sqlite3.Row
 if not write:c.execute('PRAGMA query_only=ON')
 return c
def tables(c):return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
def update_running(db):
 with connect(db,timeout=.2) as c:
  if 'jobs' not in tables(c):return False
  return bool(c.execute("SELECT 1 FROM jobs WHERE status='RUNNING' AND heartbeat>? LIMIT 1",(time.time()-180,)).fetchone())
def read_calendar(project,db):
 import sys
 root=str(Path(project).resolve())
 if root not in sys.path:sys.path.insert(0,root)
 from chart_recovery.repository import Repository
 with Repository(db) as r:
  return r.calendar(r.base())
