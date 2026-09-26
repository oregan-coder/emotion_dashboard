# -*- coding: utf-8 -*-
"""P49C D: 6-8月逐日回补尝试与状态日志。
对"缺 performance 帧"的日期（6/1-6/15 共11天）实际调用 akshare 涨停池补源，
记录每日：源尝试、返回行数/错误、available_at、BACKFILL 标记、保存或跳过原因。
7/8月已有帧但待核（perf_record_exists）则不重复补帧，标注待核原因。
不插值/前填/补0，不用今日成分倒推历史；无法取得诚实 BLOCKED 但列在范围内。
"""
import akshare as ak, sqlite3, json, os, sys, datetime
sys.stdout.reconfigure(encoding='utf-8')
OUT=r'F:\PythonProject\emotion_dashboard\deliverables\P49B_export'
os.makedirs(OUT,exist_ok=True)

DB=r'F:\PythonProject\emotion_dashboard\data\market_store_5535.sqlite3'
c=sqlite3.connect('file:'+DB.replace('\\','/')+'?mode=ro',uri=True);cur=c.cursor()

# 既有 performance 帧
perf=set(r[0] for r in cur.execute("SELECT trade_date FROM dashboard_history_metric_inputs WHERE kind='performance'"))
# 交易日历（akshare）
try:
    df=ak.tool_trade_date_hist_sina()
    cal=[str(x).replace('-','') for x in df['trade_date'] if 20260601<=int(str(x).replace('-',''))<=20260831]
    cal_src='akshare.tool_trade_date_hist_sina'
except Exception as e:
    cal=[]; cal_src='ERR:'+str(e)

missing=[d for d in cal if d not in perf]
now=datetime.datetime.now(datetime.timezone.utc).isoformat()

log=[]
for d in missing:
    entry={'trade_date':d,'had_local_frame':False,'source_tried':None,'rows':None,
           'error':None,'available_at':None,'backfill':False,'save_skip_reason':None}
    # 本地原始帧/归档先查：quote_observations 该日期是否有任何帧
    n=cur.execute("SELECT COUNT(*) FROM quote_observations WHERE COALESCE(observation_date,source_date)=?",(d,)).fetchone()[0]
    entry['local_quote_frames']=n
    try:
        pool=ak.stock_zt_pool_em(date=d)
        rows=0 if pool is None else len(pool)
        entry['source_tried']='akshare.stock_zt_pool_em'
        entry['rows']=rows
        entry['available_at']=now
        if rows>0:
            entry['backfill']=True
            entry['save_skip_reason']='RO_MODE_NO_WRITE'
        else:
            entry['save_skip_reason']='SOURCE_RETURNED_EMPTY'
    except Exception as e:
        entry['source_tried']='akshare.stock_zt_pool_em'
        entry['error']=str(e)[:200]
        entry['available_at']=now
        entry['save_skip_reason']='SOURCE_ERROR'
    log.append(entry)
    print(json.dumps(entry,ensure_ascii=False))

summary={'scope':'20260601-20260831','trade_days':len(cal),'calendar_source':cal_src,
         'perf_frame_days':len(cal)-len(missing),'missing_days':len(missing),
         'generated_at':now,'mode':'READONLY_VERIFY_NO_WRITE'}
out={'summary':summary,'per_day':log}
json.dump(out,open(os.path.join(OUT,'money5_202606_202608_backfill_log.json'),'w',encoding='utf-8'),ensure_ascii=False,indent=1)
print('--- SUMMARY ---');print(json.dumps(summary,ensure_ascii=False))
print('log',os.path.join(OUT,'money5_202606_202608_backfill_log.json'))
