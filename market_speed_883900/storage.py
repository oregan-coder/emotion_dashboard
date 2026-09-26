"""Additive data/serving tables. Existing market/research values are never changed.
Lightweight triggers increment a DISPLAY version only at relevant commits.
Jobs, heartbeats, HTTP traces and cache writes are deliberately NOT dependencies.
"""
from __future__ import annotations
import json,sqlite3,time
from .common import *
PREFIX='m8839_'
SCHEMA='''
CREATE TABLE IF NOT EXISTS m8839_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
INSERT OR IGNORE INTO m8839_meta VALUES('display_epoch','1');
INSERT OR IGNORE INTO m8839_meta VALUES('index_active','0');
CREATE TABLE IF NOT EXISTS m8839_response(id TEXT PRIMARY KEY,provider TEXT NOT NULL,code TEXT NOT NULL,received_at TEXT NOT NULL,url TEXT,raw_text TEXT NOT NULL,metadata_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS m8839_daily(id TEXT PRIMARY KEY,trade_date TEXT NOT NULL,code TEXT NOT NULL CHECK(code='883900'),pct REAL NOT NULL,close_value REAL,preclose_value REAL,method TEXT NOT NULL,response_id TEXT NOT NULL,payload_json TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS m8839_heads(trade_date TEXT PRIMARY KEY,revision_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS m8839_cache(cache_key TEXT PRIMARY KEY,epoch INTEGER NOT NULL,trade_date TEXT NOT NULL,built_at REAL NOT NULL,build_ms REAL NOT NULL,raw BLOB NOT NULL,zipped BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS m8839_runs(id TEXT PRIMARY KEY,kind TEXT NOT NULL,started_at REAL NOT NULL,finished_at REAL,status TEXT NOT NULL,detail_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS m8839_leases(name TEXT PRIMARY KEY,owner TEXT NOT NULL,expires_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS m8839_daily_date ON m8839_daily(trade_date);
'''
# Heads/published rows are cheap and change only when business content changes.
DEPENDENCIES={
 'published_days':None,'dashboard_derived_heads':None,'dashboard_history_metric_heads':None,
 'history_archive_days':None,'chart_recovery_records':None,'m8839_heads':None,
 'p50_heads':"{row}.kind IN ('calendar','daily_performance','smash','original_dashboard','bar','provider_response','serving','control')",
 'source_receipts':"{row}.status='VALID'",
}
def install_schema(db):
 with connect(db,True,timeout=10) as c:
  c.executescript(SCHEMA)
  existing=tables(c)
  for table,condition in DEPENDENCIES.items():
   if table not in existing:continue
   for event,row in [('INSERT','NEW'),('UPDATE','NEW'),('DELETE','OLD')]:
    cond=('WHEN '+('('+condition.format(row='NEW')+') OR ('+condition.format(row='OLD')+')' if event=='UPDATE' else condition.format(row=row))) if condition else ''
    name=f'm8839_epoch_{table}_{event.lower()}'
    c.execute(f'''CREATE TRIGGER IF NOT EXISTS "{name}" AFTER {event} ON "{table}" {cond}
      BEGIN UPDATE m8839_meta SET value=CAST(value AS INTEGER)+1 WHERE key='display_epoch'; END''')
  c.execute('''CREATE TRIGGER IF NOT EXISTS m8839_epoch_active AFTER UPDATE OF value ON m8839_meta
   WHEN NEW.key='index_active' AND NEW.value<>OLD.value
   BEGIN UPDATE m8839_meta SET value=CAST(value AS INTEGER)+1 WHERE key='display_epoch'; END''')
  c.commit()
 return {'added_tables':[r for r in sorted(existing) if r.startswith(PREFIX)],'market_rows_changed':0,'display_triggers':True}
def epoch(db):
 with connect(db,timeout=.05) as c:
  r=c.execute("SELECT value FROM m8839_meta WHERE key='display_epoch'").fetchone()
  if not r:raise ValueError('显示版本未初始化')
  return int(r[0])
def invalidate(db):
 with connect(db,True,timeout=2) as c:c.execute("UPDATE m8839_meta SET value=CAST(value AS INTEGER)+1 WHERE key='display_epoch'");c.commit()
def active(db):
 with connect(db) as c:
  if 'm8839_meta' not in tables(c):return False
  r=c.execute("SELECT value FROM m8839_meta WHERE key='index_active'").fetchone();return bool(r and r[0]=='1')
def daily_rows(db):
 with connect(db) as c:
  if 'm8839_heads' not in tables(c):return {}
  rows=c.execute('SELECT d.* FROM m8839_heads h JOIN m8839_daily d ON d.id=h.revision_id AND d.trade_date=h.trade_date ORDER BY d.trade_date')
  return {r['trade_date']:dict(r) for r in rows}
def save_index(db,bundle,activate=False):
 """One short transaction; raw evidence + immutable revisions + heads. Idempotent."""
 rows=bundle['daily'];resp=bundle['response'];rid=resp['id'];new=0
 with connect(db,True,timeout=5) as c:
  c.execute('INSERT OR IGNORE INTO m8839_response VALUES(?,?,?,?,?,?,?)',
   (rid,resp['provider'],CODE,resp['received_at'],resp.get('url'),resp['raw_text'],dumps(resp.get('metadata',{}))))
  for r in rows:
   data=dict(r,code=CODE,response_id=rid);ident=digest(data)
   c.execute('INSERT OR IGNORE INTO m8839_daily VALUES(?,?,?,?,?,?,?,?,?,?)',
    (ident,r['date'],CODE,r['pct'],r.get('close'),r.get('preclose'),r['method'],rid,dumps(data),now_iso()))
   old=c.execute('SELECT revision_id FROM m8839_heads WHERE trade_date=?',(r['date'],)).fetchone()
   if not old or old[0]!=ident:
    c.execute('INSERT INTO m8839_heads VALUES(?,?) ON CONFLICT(trade_date) DO UPDATE SET revision_id=excluded.revision_id',(r['date'],ident));new+=1
  if activate:c.execute("UPDATE m8839_meta SET value='1' WHERE key='index_active'")
  c.commit()
 return {'new_or_revised_days':new,'activated':active(db),'table':'m8839_daily','source':SERIES}
def set_active(db,value):
 with connect(db,True,timeout=2) as c:c.execute("UPDATE m8839_meta SET value=? WHERE key='index_active'",('1' if value else '0',));c.commit()
def lease(db,name,owner,seconds=60):
 with connect(db,True,timeout=.2) as c:
  c.execute('BEGIN IMMEDIATE');now=time.time();r=c.execute('SELECT owner,expires_at FROM m8839_leases WHERE name=?',(name,)).fetchone()
  if r and r['owner']!=owner and r['expires_at']>now:return False
  c.execute('INSERT INTO m8839_leases VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET owner=excluded.owner,expires_at=excluded.expires_at',(name,owner,now+seconds));c.commit();return True
def release(db,name,owner):
 with connect(db,True,timeout=2) as c:c.execute('DELETE FROM m8839_leases WHERE name=? AND owner=?',(name,owner));c.commit()
def save_run(db,ident,kind,started,status,detail):
 with connect(db,True,timeout=2) as c:
  c.execute('INSERT OR REPLACE INTO m8839_runs VALUES(?,?,?,?,?,?)',(ident,kind,started,time.time(),status,dumps(detail)));c.commit()

def install_lookup_indexes(db):
 """Indexes only, no row mutation. Query stays source-date/identity checked."""
 made=[]
 with connect(db,True,timeout=10) as c:
  ts=tables(c)
  definitions={
   'source_rows':('m8839_source_batch_frame','batch_id,frame,row_no'),
   'source_receipts':('m8839_receipt_batch_interface','batch_id,interface'),
   'quote_observations':('m8839_quote_day_code','trade_date,code'),
  }
  for table,(name,cols) in definitions.items():
   names={r[1] for r in c.execute(f'PRAGMA table_info("{table}")')} if table in ts else set()
   if set(cols.split(','))<=names:c.execute(f'CREATE INDEX IF NOT EXISTS {name} ON {table}({cols})');made.append(name)
  if 'p50_revisions' in ts:
   c.execute("CREATE INDEX IF NOT EXISTS m8839_provider_lookup ON p50_revisions(kind,json_extract(payload_json,'$.capability'),json_extract(payload_json,'$.request.code'),id) WHERE kind='provider_response' AND json_valid(payload_json)");made.append('m8839_provider_lookup')
  c.commit()
 return made
