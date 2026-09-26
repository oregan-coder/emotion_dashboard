# -*- coding: utf-8 -*-
"""P49C E: 6-8月 money5 覆盖导出器（修复 B07 七项缺陷）。
修复点：
1. perf_frame_days 拆成 record_exists / record_valid，DATA_PENDING 也算"记录存在"。
2. published_batch 沿真实发布指针 published_days JOIN batches，输出批次ID + money5 revision ID。
3. 六月"无 performance 帧"与"无 money5 派生"分开两个维度计数。
4. VALID 需有限数值检查，保留 0/负值，拒绝 None/NaN/Infinity/bool。
5. 多版本复用主站选中规则 dashboard_derived_heads（revision_id 指向的行）。
6. DB 路径从配置解析、只读连接、确认文件存在。
7. CSV 与月汇总同一次读取、同一选择规则，保留来源 ID 与精度；四舍五入仅展示。
"""
import sqlite3, json, csv, os, sys, math
sys.stdout.reconfigure(encoding='utf-8')

def read_config():
    cfgp=r'F:\PythonProject\emotion_dashboard\5535_automation.json'
    if not os.path.exists(cfgp):
        raise SystemExit('CONFIG_MISSING '+cfgp)
    with open(cfgp,encoding='utf-8') as f: return json.load(f)

cfg=read_config()
DB=cfg.get('database') or r'F:\PythonProject\emotion_dashboard\data\market_store_5535.sqlite3'
OUT=os.path.join(r'F:\PythonProject\emotion_dashboard\deliverables','P49B_export')
if not os.path.exists(DB):
    raise SystemExit('DB_MISSING '+DB)
os.makedirs(OUT,exist_ok=True)
# 只读连接
try:
    c=sqlite3.connect('file:'+DB.replace('\\','/')+'?mode=ro',uri=True)
except sqlite3.Error as e:
    raise SystemExit('RO_CONNECT_FAIL '+str(e))
cur=c.cursor()

def finite_number(v):
    return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)

# 交易日历：优先 akshare 真实日历，失败则从 DB 已存历史性能/派生日期推导（标注降级）
cal=[]
try:
    import akshare as ak
    df=ak.tool_trade_date_hist_sina()
    cal=[str(x).replace('-','') for x in df['trade_date']
         if 20260601<=int(str(x).replace('-',''))<=20260831]
    cal_src='akshare.tool_trade_date_hist_sina'
except Exception as e:
    seen=set()
    for r in cur.execute("SELECT trade_date FROM dashboard_history_metric_inputs"):
        seen.add(r[0])
    for r in cur.execute("SELECT trade_date FROM dashboard_derived_metrics"):
        seen.add(r[0])
    cal=sorted(d for d in seen if 20260601<=int(d)<=20260831)
    cal_src='DB_INFERRED:'+str(e)

# 发布指针：published_days JOIN batches（真实选中规则）
published={}
for r in cur.execute("SELECT p.trade_date,b.id,b.input_sha256,b.snapshot_sha256 FROM published_days p JOIN batches b ON b.id=p.batch_id"):
    published[r[0]]={'batch_id':r[1],'input_sha256':r[2],'snapshot_sha256':r[3]}
# 任意 batches 行（非发布证明）
any_batch=set(r[0] for r in cur.execute("SELECT DISTINCT trade_date FROM batches"))

# money5 选中修订：dashboard_derived_heads 的 revision_id
heads={}
for r in cur.execute("SELECT source_batch_id,metric,rule_version,revision_id FROM dashboard_derived_heads WHERE metric='money5'"):
    heads.setdefault(r[0],[]).append({'rule_version':r[2],'revision_id':r[3]})
rev_payload={}
for r in cur.execute("SELECT id,trade_date,status,value_real,payload_json FROM dashboard_derived_metrics WHERE metric='money5'"):
    rev_payload[r[0]]={'trade_date':r[1],'status':r[2],'value_real':r[3],'payload':json.loads(r[4]) if r[4] else {}}

# performance 输入帧（kind='performance'）
perf={}
for r in cur.execute("SELECT trade_date,id,status,payload_json FROM dashboard_history_metric_inputs WHERE kind='performance'"):
    try:p=json.loads(r[3])
    except:continue
    perf[r[0]]={'id':r[1],'status':r[2],'value':p.get('value'),'issues':p.get('issues') or [],
                'available_at':p.get('available_at'),'source':p.get('source'),
                'fallback_used':p.get('fallback_used')}

def money5_for_date(d):
    """按主站选中规则返回该日的 money5 派生（published batch -> heads revision）。"""
    pub=published.get(d)
    if not pub: return None
    hs=heads.get(pub['batch_id']) or []
    if not hs: return None
    rev=rev_payload.get(hs[0]['revision_id'])
    if rev is None: return None
    return {'batch_id':pub['batch_id'],'revision_id':hs[0]['revision_id'],
            'rule_version':hs[0]['rule_version'],'trade_date':rev['trade_date'],
            'status':rev['status'],'value_real':rev['value_real'],'payload':rev['payload']}

rows=[]
for d in cal:
    pf=perf.get(d)
    pub=published.get(d)
    m=money5_for_date(d)
    # 记录存在 vs 记录有效（performance 帧）
    record_exists = pf is not None
    # 日值：仅当帧存在且 VALID 且 value 为有限数值（保留 0/负值）才给有效值
    daily_valid = record_exists and pf['status']=='VALID' and finite_number(pf['value'])
    if daily_valid:
        daily_val=round(float(pf['value']),4); daily_st='VALID'
    else:
        daily_val=''
        daily_st = ('NO_FRAME' if not record_exists else
                    ('DATA_PENDING' if pf['status']!='VALID' else 'NOT_FINITE_VALUE'))
    # 五日均值：选中修订
    if m is not None and m['status']=='VALID' and finite_number(m['value_real']):
        fc_val=round(float(m['value_real']),4); fc_st='VALID'; fc_rule=m['rule_version']; fc_rev=m['revision_id']
    else:
        fc_val=''; fc_st=('NO_DERIVED' if m is None else m['status']); fc_rule=(m['rule_version'] if m else ''); fc_rev=(m['revision_id'] if m else '')
    rows.append({'date':d,
                 'published':pub is not None,'published_batch_id':(pub['batch_id'] if pub else ''),
                 'any_batch':d in any_batch,
                 'perf_record_exists':record_exists,
                 'perf_frame':(pf['status'] if record_exists else 'NO_FRAME'),
                 'perf_available_at':(pf.get('available_at') if record_exists else None),
                 'daily_value':daily_val,'daily_status':daily_st,
                 'daily_issues':(';'.join(pf['issues']) if record_exists and pf['issues'] else ('NO_PERF_FRAME' if not record_exists else daily_st)),
                 'fund_cycle_value':fc_val,'fund_cycle_status':fc_st,
                 'fund_cycle_rule_version':fc_rule,'fund_cycle_revision_id':fc_rev,
                 'fund_cycle_reason':((m['payload'].get('reason') if m and m.get('payload') else None) or ('NO_DERIVED_RECORD' if m is None else m['status']))})

# 逐日 CSV
csvp=os.path.join(OUT,'money5_202606_202608_daily.csv')
with open(csvp,'w',newline='',encoding='utf-8-sig') as f:
    w=csv.writer(f)
    w.writerow(['date','published','published_batch_id','any_batch','perf_record_exists','perf_frame',
                'perf_available_at','daily_value','daily_status','daily_issues',
                'fund_cycle_value','fund_cycle_status','fund_cycle_rule_version','fund_cycle_revision_id',
                'fund_cycle_reason'])
    for r in rows:
        w.writerow([r['date'],r['published'],r['published_batch_id'],r['any_batch'],r['perf_record_exists'],
                    r['perf_frame'],r['perf_available_at'],r['daily_value'],r['daily_status'],r['daily_issues'],
                    r['fund_cycle_value'],r['fund_cycle_status'],r['fund_cycle_rule_version'],
                    r['fund_cycle_revision_id'],r['fund_cycle_reason']])

# 月汇总：四维分开
def month_rows(mm): return [r for r in rows if r['date'][:6]==mm]
summary=[]
for mm in ('202606','202607','202608'):
    rr=month_rows(mm)
    summary.append({
        'month':mm,'trade_days':len(rr),
        'published_days':sum(r['published'] for r in rr),
        'published_batch_ids':sorted({r['published_batch_id'] for r in rr if r['published']}),
        'any_batch_days':sum(r['any_batch'] for r in rr),
        'perf_record_exists':sum(r['perf_record_exists'] for r in rr),
        'perf_record_pending':sum(r['perf_record_exists'] and r['perf_frame']!='VALID' for r in rr),
        'perf_frame_days':sum(r['perf_record_exists'] for r in rr),  # 记录存在（含 pending）
        'no_performance_frame_days':[r['date'] for r in rr if not r['perf_record_exists']],
        'daily_valid':sum(r['daily_status']=='VALID' for r in rr),
        'daily_pending_dates':[r['date'] for r in rr if r['daily_status']!='VALID'],
        'fund_cycle_valid':sum(r['fund_cycle_status']=='VALID' for r in rr),
        'fund_cycle_pending_dates':[r['date'] for r in rr if r['fund_cycle_status']!='VALID'],
        'no_money5_derived_days':[r['date'] for r in rr if r['fund_cycle_status']=='NO_DERIVED'],
    })
jsonp=os.path.join(OUT,'money5_202606_202608_summary.json')
json.dump({'calendar_source':cal_src,'calendar_days':len(cal),
           'selection_rule':'published_days JOIN batches -> dashboard_derived_heads(money5) revision',
           'generated_at':'2026-09-15T00:00:00+08:00','rows':summary},
          open(jsonp,'w',encoding='utf-8'),ensure_ascii=False,indent=1)

print('cal_src',cal_src,'days',len(cal))
print('8/26-28:',[(r['date'],r['daily_status'],r['daily_value'],r['fund_cycle_status']) for r in rows if r['date'] in ('20260826','20260827','20260828')])
print('6月 no_perf_frame:',[r['date'] for r in rows if r['date'][:6]=='202606' and not r['perf_record_exists']])
print('6月 no_derived:',[r['date'] for r in rows if r['date'][:6]=='202606' and r['fund_cycle_status']=='NO_DERIVED'])
print('--- summary ---')
for s in summary: print(json.dumps(s,ensure_ascii=False))
print('CSV',csvp)
