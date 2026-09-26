"""Read-only, bounded evidence extraction on the real host. Never repairs a value.

It exports selected raw incident records plus actual canonical coverage and publication
state. No CSV, no SDK network access, no original-table writes, no manual PASS flags.
"""
from __future__ import annotations
import argparse,sys,json,hashlib,urllib.request,urllib.parse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from p50fix.db import Store
from p50fix.common import resolve_db,read_json,write_json,day
from p50fix.pipeline import closed_end
from p50fix.audit import coverage_report
CODES=('603400','000565','002377','600192')
BATCHES=('d9bc3e1bd54c4f93928b43bb12b045d7','5139dea6676c4dd39bb96d46965448a0')
SUPPORT='64474cddec5a0ccfb0228a4acf8b1834874a7f425f2a65278063e22f5b2ef90c'

def redact(obj):
    if isinstance(obj,dict):
        return {k:('[REDACTED]' if any(t in k.lower() for t in ('token','password','authorization','cookie','api_key','secret')) else redact(v)) for k,v in obj.items()}
    if isinstance(obj,list):return [redact(v) for v in obj]
    return obj

def select_rows(store,table,where='',params=(),limit=5000):
    allowed={'source_rows','source_receipts','quote_observations','dashboard_history_metric_inputs','dashboard_history_metric_heads','dashboard_derived_metrics','published_days','batches'}
    if table not in allowed:raise ValueError('TABLE_NOT_ALLOWED')
    if table not in store.schema():return {'status':'TABLE_ABSENT','rows':[]}
    try:
        # All SQL fragments originate in the fixed queries below, never CLI input.
        cursor=store.conn.execute('SELECT * FROM "'+table+'"'+(' WHERE '+where if where else '')+' LIMIT ?',(*params,limit+1))
        rows=[dict(r) for r in cursor];truncated=len(rows)>limit
        for r in rows[:limit]:
            for k in ('payload_json','receipt_json'):
                if k in r and isinstance(r[k],str):
                    try:r[k]=json.loads(r[k])
                    except ValueError:pass
        return {'status':'TRUNCATED' if truncated else 'EXPORTED','limit':limit,'rows':redact(rows[:limit])}
    except Exception as exc:return {'status':'SCHEMA_QUERY_BLOCKED','error':str(exc),'rows':[]}

def collect(store,start,end):
    result={'database':str(store.path),'scope':'READ_ONLY_HOST_EVIDENCE','start':start,'end':end,
            'schema':store.schema(),'writes':False,'is_acceptance':False}
    try:result['coverage']=coverage_report(store,start,end)
    except Exception as exc:result['coverage_error']=str(exc)
    for kind,key in [('control','active'),('control','update_status'),('calendar','CN_A'),('security_master','CN_A')]:
        o=store.get(kind,key)
        if kind=='security_master' and o:
            data=o['data'];members=data.get('members',{})
            o={'id':o['id'],'metadata':{k:v for k,v in data.items() if k!='members'},'member_count':len(members),
               'missing_type_count':sum(str(x.get('type','')) not in {'1','2','3'} for x in members.values()),
               'selected_members':{c:members[c] for c in CODES if c in members}}
        result[kind+':'+key]=o
    result['incidents']={}
    for d,cs in [('20260911',CODES[1:]),('20260915',CODES[:1])]:
        ent={}
        for kind in ('original_dashboard','daily_performance','smash','money5'):
            ent[kind]=store.get(kind,d)
        for c in cs:
            ent['bar:'+c]=store.get('bar',d+':'+c)
            ent['bar_candidates:'+c]=store.list('bar_candidate',d+':'+c+':',d+':'+c+':\uffff')
        ent['published_payload']=store.get('serving','/api/dashboard|date='+d)
        result['incidents'][d]=ent
    result['provider_responses']=[]
    for k,rid,o in store.list('provider_response'):
        req=o.get('request') or {}
        if req.get('code') in CODES:
            result['provider_responses'].append({'key':k,'id':rid,'data':o})
            if len(result['provider_responses'])>=200:break
    result['provider_attempts']=[dict(r) for r in store.conn.execute('SELECT * FROM p50_attempts ORDER BY id DESC LIMIT 200')]
    result['source_rows_incident_frames']=select_rows(store,'source_rows','batch_id IN (?,?)',BATCHES,10000)
    ph=','.join('?' for _ in CODES)
    result['incident_observations']=select_rows(store,'quote_observations',f'code IN ({ph}) AND observation_date>=? AND observation_date<=?',(*CODES,start,end),20000)
    result['incident_receipts']=select_rows(store,'source_receipts','batch_id IN (?,?)',BATCHES,2000)
    result['history_input_heads']=select_rows(store,'dashboard_history_metric_heads','trade_date>=? AND trade_date<=?',(start,end))
    result['history_support_inputs']=select_rows(store,'dashboard_history_metric_inputs','id=? OR trade_date IN (?,?)',(SUPPORT,'20260911','20260915'))
    result['derived_incidents']=select_rows(store,'dashboard_derived_metrics','trade_date IN (?,?)',('20260911','20260915'))
    result['published_days']=select_rows(store,'published_days','trade_date>=? AND trade_date<=?',(start,end))
    return redact(result)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--project',required=True);ap.add_argument('--out',required=True);ap.add_argument('--base');args=ap.parse_args()
    project=Path(args.project).resolve();cfg=read_json(project/'p50_config.json')
    db=resolve_db(project/cfg.get('automation_config','5535_automation.json'))
    out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=True)
    with Store(db,readonly=True) as store:
        with store.transaction(write=False):result=collect(store,day(cfg.get('start','20260701')),day(cfg.get('end') or closed_end()))
    write_json(out/'database_evidence.json',result)
    if args.base:
        u=urllib.parse.urlparse(args.base)
        if u.scheme not in {'http','https'} or u.hostname not in {'127.0.0.1','localhost','::1'}:raise ValueError('LOCAL_HTTP_ONLY')
        paths=['/api/health','/api/dashboard?date=20260915','/api/dashboard?date=20260911','/api/dashboard?date=20260701','/api/history','/api/dates','/api/research/money-effect?date=20260915']
        paths+=cfg.get('host_smoke_paths',[]);logs=[]
        for i,path in enumerate(dict.fromkeys(paths)):
            if not path.startswith('/api/') or '://' in path:raise ValueError('INVALID_PATH')
            try:
                with urllib.request.urlopen(args.base.rstrip('/')+path,timeout=45) as r:
                    raw=r.read();body=json.loads(raw);headers=dict(r.headers);status=r.status
                filename=f'api_{i:02d}.json';write_json(out/filename,redact(body))
                logs.append({'path':path,'http_status':status,'file':filename,'source':headers.get('X-5535-Data-Source'),'unredacted_sha256':hashlib.sha256(raw).hexdigest()})
            except Exception as exc:logs.append({'path':path,'error':str(exc)[:600]})
        write_json(out/'http_manifest.json',logs)
    print(json.dumps({'status':'EVIDENCE_EXPORTED_NOT_ACCEPTANCE','output':str(out),'writes':False},ensure_ascii=False))
if __name__=='__main__':main()
