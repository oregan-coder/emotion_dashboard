"""THS883900 source + strict normalization. Never rebrands local cohort mean.
The THS URL structure/CSV column order follows AKShare's official THS index
implementation; 883900 availability is probed, never asserted by a successful
HTTP status alone. An authenticated provider may be supplied via adapter.
"""
from __future__ import annotations
import importlib,json,os,re,sys,time
from .common import *

class SourceError(ValueError):pass

def json_object(text):
 s=text.strip().lstrip('\ufeff');left=s.find('{');right=s.rfind('}')
 if left<0 or right<left:raise SourceError('不是指数JSON响应')
 body=s[left:right+1]
 try:obj=json.loads(body)
 except json.JSONDecodeError:
  # Data parser only; never eval remote JS.
  try:
   from akshare.utils import demjson
   obj=demjson.decode(body)
  except Exception as exc:raise SourceError('不支持的指数JSON格式') from exc
 if not isinstance(obj,dict):raise SourceError('指数根对象不是字典')
 return obj,s[:left]

def parse_ths(text,url):
 obj,prefix=json_object(text)
 symbol=str(obj.get('code') or obj.get('symbol') or obj.get('stockcode') or '')
 name=str(obj.get('name') or obj.get('stockname') or '')
 candidates=[obj]
 if isinstance(obj.get('data'),dict):candidates.append(obj['data'])
 # JSONP function is native response content, not the request date/code copied in.
 code_proof=bool(re.search(r'(?<!\d)883900(?!\d)',symbol+' '+prefix))
 if not code_proof:raise SourceError('响应没有883900身份字段或对应原生回调标识')
 if name and not any(n in name for n in ('昨日涨停','昨涨停')):raise SourceError('响应指数名称与883900不符: '+name)
 values=None
 for candidate in candidates:
  data=candidate.get('data')
  if isinstance(data,(str,list)):values=data;break
 if values is None:raise SourceError('响应没有可识别的日线数据')
 rows=[]
 if isinstance(values,str):
  # AKShare source defines date/open/high/low/close/volume/turnover here.
  for line in values.split(';'):
   if not line.strip():continue
   a=line.split(',')
   if len(a)<5 or not day(a[0]):raise SourceError('日线列结构或原生日份日期无效')
   rows.append(dict(zip(('date','open','high','low','close','volume','turnover'),a[:7])))
 else:
  for r in values:
   if not isinstance(r,dict):raise SourceError('未声明列定义的数组日线不接受')
   rows.append(r)
 return {'code':CODE,'name':name or NAME,'rows':rows,'identity_proof':{'response_code':symbol,'callback':prefix[:200],'name':name},'url':url}

def normalize(source,calendar,start,end,raw_text,provider='THS_WEB',url=None):
 if str(source.get('code')) not in ('883900','883900.TI'):raise SourceError('仅接受883900，不能默认替代为其他指数')
 cal=sorted(set(calendar));pos={d:i for i,d in enumerate(cal)}
 if not day(start) or not day(end) or start>end:raise SourceError('日期范围无效')
 bars={};rejected=[]
 for r in source.get('rows',[]):
  d=day(r.get('date') or r.get('trade_date') or r.get('日期'))
  symbol=r.get('code',r.get('ts_code'))
  if symbol is not None and str(symbol) not in ('883900','883900.TI'):raise SourceError('日线中混有其他代码')
  if not d:raise SourceError('不能把请求日期当作来源日期')
  if d not in pos or d>end:continue
  close=number(r.get('close',r.get('收盘价',r.get('收盘'))))
  pre=number(r.get('pre_close',r.get('preclose')))
  pct=number(r.get('pct_change',r.get('pctChg',r.get('涨跌幅'))))
  high=number(r.get('high'));low=number(r.get('low'));op=number(r.get('open'))
  if close is not None and close<=0:raise SourceError('指数收盘值必须大于0')
  if pre is not None and pre<=0:raise SourceError('指数前收盘值必须大于0')
  if high is not None and low is not None and (high<low or (close is not None and not low-1e-6<=close<=high+1e-6) or (op is not None and not low-1e-6<=op<=high+1e-6)):
   raise SourceError('OHLC字段位置/数值自相矛盾')
  b={'date':d,'close':close,'preclose':pre,'pct':pct}
  if d in bars and bars[d]!=b:raise SourceError('同日响应重复且数值冲突')
  bars[d]=b
 out=[]
 for d,b in sorted(bars.items()):
  if d<start:continue
  pct=b['pct'];pre=b['preclose'];close=b['close'];method='NATIVE_INDEX_PCT'
  prev=cal[pos[d]-1] if pos[d]>0 else None
  if pre is None and prev in bars:pre=bars[prev]['close']
  calc=(close/pre-1)*100 if close is not None and pre is not None else None
  if pct is not None and calc is not None and abs(pct-calc)>.03:
   raise SourceError('原生涨幅与收盘/前收盘冲突: '+d)
  if pct is None:
   if calc is None:rejected.append({'date':d,'reason':'缺原生涨幅或相邻交易日同指数收盘'});continue
   pct=calc;method='SAME_INDEX_VERIFIED_ADJACENT_CLOSE_CHANGE'
  if not -100<pct<100:raise SourceError('日涨幅异常，拒绝混入指数点位: '+d)
  out.append({'date':d,'pct':pct,'close':close,'preclose':pre,'method':method,'source_date':d,'status':'VALID','unit':'%','source':SERIES})
 if not out:raise SourceError('没有范围内可验证的883900日值')
 rid=digest({'provider':provider,'raw':raw_text,'code':CODE})
 return {'daily':out,'rejected':rejected,'response':{'id':rid,'provider':provider,'code':CODE,'url':url,'received_at':now_iso(),'raw_text':raw_text,'metadata':{'identity':source.get('identity_proof'), 'range':[start,end],'raw_dates':sorted(bars)}}}

def fetch_realhead_today(calendar, end):
    """Fetch today's bar from THS realhead when line K-line lags end-of-day."""
    import requests
    url = 'https://d.10jqka.com.cn/v6/realhead/48_883900/last.js'
    headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15',
        'Referer': 'https://m.10jqka.com.cn/',
    }
    r = requests.get(url, headers=headers, timeout=(3.05, 6))
    r.raise_for_status()
    text = r.text
    m = re.search(r'^[^(]+\((.*)\)\s*;?\s*$', text, re.S)
    if not m:
        raise SourceError('realhead: 无法解析JSONP包装')
    obj = json.loads(m.group(1))
    items = obj.get('items', {})
    code_val = str(items.get('5', '')).strip()
    if code_val != CODE:
        raise SourceError(f'realhead: 代码不匹配 got={code_val}')
    raw_time = str(items.get('updateTime') or items.get('time', ''))
    date_str = raw_time.strip()[:10].replace('-', '')
    if date_str != end:
        raise SourceError(f'realhead: 日期不匹配 got={date_str} want={end}')
    close = number(items.get('10'))
    preclose = number(items.get('6'))
    pct = number(items.get('199112'))
    op = number(items.get('7'))
    high = number(items.get('8'))
    low = number(items.get('9'))
    if close is None or close <= 0:
        raise SourceError('realhead: 收盘值无效')
    row = {'date': date_str, 'open': op, 'high': high, 'low': low,
           'close': close, 'pre_close': preclose, 'pct_change': pct}
    return row, text, url


def fetch_source(start,end,calendar,mode='history',adapter=None):
 """Invoked in a bounded subprocess. Does not write the database."""
 if adapter:
  module,func=adapter.rsplit(':',1)
  result=getattr(importlib.import_module(module),func)(code=CODE,start=start,end=end)
  if not isinstance(result,dict) or not isinstance(result.get('raw_text'),str):raise SourceError('adapter必须返回code/rows/raw_text原始证据')
  return normalize(result,calendar,start,end,result['raw_text'],result.get('provider','USER_AUTHORIZED_THS'),result.get('url'))
 import requests
 attempts=[];suffix='last' if mode=='latest' else end[:4]
 # Bounded known public wire formats; exact code is checked in response itself.
 urls=[f'https://d.10jqka.com.cn/v4/line/bk_883900/01/{suffix}.js',
       f'https://d.10jqka.com.cn/v6/line/48_883900/01/{suffix}.js']
 if start[:4]!=end[:4] and mode=='history':
  raise SourceError('跨年度请分年采集并带前一年末的原生前收/涨幅；拒绝跳年算涨幅')
 for url in urls:
  try:
   headers={'User-Agent':'Mozilla/5.0','Referer':'https://q.10jqka.com.cn/'}
   if os.environ.get('THS_COOKIE'):headers['Cookie']=os.environ['THS_COOKIE']
   r=requests.get(url,headers=headers,timeout=(3.05,6))
   if r.status_code in (401,403,429):
    attempts.append({'host':'d.10jqka.com.cn','status':r.status_code,'message':'受限，停止同域重试'});break
   r.raise_for_status();r.encoding=r.apparent_encoding or 'utf-8'
   parsed=parse_ths(r.text,url)
   # If line K-line doesn't include end date (today), supplement from realhead.
   existing_dates={row.get('date') or row.get('trade_date') or row.get('日期') for row in parsed.get('rows',[])}
   if end not in existing_dates:
    try:
     rh_row, rh_text, rh_url = fetch_realhead_today(calendar, end)
     parsed['rows'].append(rh_row)
     attempts.append({'url':rh_url,'status':200,'note':'realhead补充当日bar'})
    except Exception as rh_exc:
     attempts.append({'url':'realhead','error_type':type(rh_exc).__name__,'error':str(rh_exc)[:180]})
   bundle=normalize(parsed,calendar,start,end,r.text,'THS_WEB',url)
   bundle['attempts']=attempts+[{'url':url,'status':200,'valid_days':len(bundle['daily'])}];return bundle
  except Exception as exc:attempts.append({'url':url,'error_type':type(exc).__name__,'error':str(exc)[:180]})
 # Existing optional permission only; no purchase or token file handling.
 token=os.environ.get('TUSHARE_TOKEN')
 if token:
  try:
   r=requests.post('https://api.tushare.pro',json={'api_name':'ths_daily','token':token,'params':{'ts_code':'883900.TI','start_date':start,'end_date':end},'fields':'ts_code,trade_date,open,high,low,close,pre_close,pct_change'},timeout=(3.05,6));r.raise_for_status();body=r.json()
   if body.get('code')!=0:raise SourceError('Tushare权限或数据错误，code='+str(body.get('code')))
   data=body.get('data') or {};rows=[dict(zip(data.get('fields',[]),a)) for a in data.get('items',[])]
   # API must return exact symbol for every row; code isn't inferred from request.
   if not rows or any(x.get('ts_code')!='883900.TI' for x in rows):raise SourceError('Tushare883900返回为空或代码不匹配')
   return normalize({'code':'883900.TI','rows':rows,'identity_proof':{'native_ts_code':'883900.TI'}},calendar,start,end,r.text,'TUSHARE_THS','https://api.tushare.pro/ths_daily')
  except Exception as exc:attempts.append({'provider':'TUSHARE_THS','error_type':type(exc).__name__})
 raise SourceError(dumps({'status':'NO_VERIFIED_883900_RESPONSE','attempts':attempts,'note':'未用其他指数/本地均值冒充883900'}))

if __name__=='__main__':
 try:
  cfg=json.loads(sys.stdin.read());b=fetch_source(**cfg);print(dumps({'ok':True,'bundle':b}))
 except Exception as exc:print(dumps({'ok':False,'error':str(exc),'error_type':type(exc).__name__}));sys.exit(2)
