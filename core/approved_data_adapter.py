"""Acquisition/normalization for the approved pipeline; no tokens or provider substitution.

A successful HTTP call is not date/completeness proof. Unknown envelopes are
retained with diagnostics; valid primary 883900 can be supplied by a verified
existing client. The default public-page attempt never interprets an unrelated
board or first numeric cell as 883900's percentage.
"""
from __future__ import annotations
import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from types import SimpleNamespace
import pandas as pd
from core.input_contracts import find_column, normalize_code, number, integer, boolean, board_count, clean_json
from core.approved_policy import TradeCalendar, day


FRAME_NAMES = ('market', 'limit_up', 'limit_down', 'open_board',
               'previous_limit_up', 'previous_pool_performance')


def capture_frame_inputs(data):
    """Capture the exact post-fetcher DataFrames before policy filtering.

    These are NOT raw HTTP responses and do not establish provider dates.
    Columns/row order and attrs are retained for deterministic replay.
    """
    frames = {}
    for name in FRAME_NAMES:
        frame = getattr(data, name, None)
        if not isinstance(frame, pd.DataFrame):
            frames[name] = {'status': 'NO_FRAME', 'columns': [], 'data': [], 'attrs': {}}
            continue
        attrs = {}
        omitted = []
        for key, value in frame.attrs.items():
            try:
                attrs[str(key)] = clean_json(value)
            except (TypeError, ValueError):
                omitted.append(str(key))
        frames[name] = {'status': 'CAPTURED_POST_FETCHER_NOT_HTTP',
                       'columns': [str(c) for c in frame.columns],
                       'dtypes': {str(c): str(frame[c].dtype) for c in frame.columns},
                       'data': clean_json(frame.astype(object).where(pd.notna(frame), None).values.tolist()),
                       'attrs': attrs, 'omitted_non_json_attrs': omitted}
    return frames


def _restore_frame(spec):
    if not isinstance(spec, dict):
        raise ValueError('Frame evidence must be an object')
    columns, rows = spec.get('columns'), spec.get('data')
    if not isinstance(columns, list) or not isinstance(rows, list) or len(columns) != len(set(columns)):
        raise ValueError('Invalid or duplicate frame columns')
    if any(not isinstance(r, list) or len(r) != len(columns) for r in rows):
        raise ValueError('Frame row length differs from columns')
    result = pd.DataFrame(rows, columns=columns, dtype=object)
    for col, dtype in (spec.get('dtypes') or {}).items():
        if col in result and str(dtype).startswith('datetime64'):
            result[col] = pd.to_datetime(result[col], errors='raise')
    attrs = spec.get('attrs') or {}
    if not isinstance(attrs, dict):
        raise ValueError('Frame attrs must be an object')
    result.attrs.update(attrs)
    return result


def receipt(frame, requested_date, interface):
    """Preserve independently supplied metadata; absence is not an implicit false
    certification. Explicit conflicting dates/finality fail closed. Provider page
    count completeness is never promoted into approved-market scope completeness.
    """
    aliases=('closing_verified','quote_finality_verified','finality_verified')
    meta={'interface':interface,'requested_date':requested_date,
          'status':'EMPTY' if frame is None or frame.empty else 'DATA_PENDING',
          'source_date':None,'date_verified':False,'complete':False,
          'closing_verified':False,'quote_finality_verified':None,'finality_verified':None,
          'retrieved_at':datetime.now(timezone(timedelta(hours=8))).isoformat(),
          'evidence_issues':[]}
    if frame is None:return meta
    attrs=dict(getattr(frame,'attrs',{}))
    declared=day(attrs.get('source_date'))
    observed=[]
    datecol=find_column(frame,['日期','交易日期','trade_date','source_date'])
    if datecol and not frame.empty:
        observed=[day(v) for v in frame[datecol]]
    good={x for x in observed if x is not None}
    if observed and (None in observed or len(good)!=1):
        meta['evidence_issues'].append('ROW_DATE_MISSING_OR_CONFLICTING')
    if declared and good and good!={declared}:
        meta['evidence_issues'].append('ATTR_AND_ROW_DATE_CONFLICT')
    source_date=declared or (next(iter(good)) if len(good)==1 else None)
    date_ok=source_date is not None and source_date==day(requested_date) and not meta['evidence_issues']
    meta.update(source_date=source_date,date_verified=date_ok,as_of=attrs.get('as_of'))
    raw_final={k:attrs[k] for k in aliases if k in attrs}
    valid_final=[v for v in raw_final.values() if type(v) is bool]
    invalid_final=any(type(v) is not bool and v is not None for v in raw_final.values())
    conflict=True in valid_final and False in valid_final
    if invalid_final:meta['evidence_issues'].append('FINALITY_FLAG_TYPE_INVALID')
    if conflict:meta['evidence_issues'].append('FINALITY_FLAG_CONFLICT')
    final=date_ok and not invalid_final and not conflict and True in valid_final
    meta['finality_source_flags']=raw_final
    meta['closing_verified']=bool(final)
    for key in aliases[1:]:
        meta[key]=attrs.get(key) if type(attrs.get(key)) is bool else None
    meta['complete']=attrs.get('complete') is True and date_ok
    for key in ('source_contract','validation_evidence','validation_method','available_at'):
        if key in attrs:meta[key]=clean_json(attrs[key])
    if date_ok:meta['status']='VALID' if len(frame) or meta['complete'] else 'EMPTY'
    elif source_date and source_date!=day(requested_date):meta['status']='DATE_MISMATCH'
    if meta['evidence_issues']:
        meta['status']='EVIDENCE_CONFLICT';meta['complete']=False;meta['closing_verified']=False
    if isinstance(attrs.get('source_transport'),dict):
        meta['source_transport']=attrs['source_transport']
        transport=attrs['source_transport'].get('summary') or {}
        meta['provider_collection_status']=transport.get('status','NOT_OBSERVED')
        meta['provider_collection_complete']=transport.get('provider_collection_complete') is True
        if transport.get('status')=='INCOMPLETE_PROVIDER_COLLECTION' or attrs['source_transport'].get('fetch_status')=='ERROR':
            meta['complete']=False;meta['status']='TRANSPORT_INCOMPLETE';meta['closing_verified']=False
    if isinstance(attrs.get('fetch_error'),dict):
        meta['fetch_error']=attrs['fetch_error'];meta['status']='ERROR';meta['complete']=False;meta['closing_verified']=False
    meta['note']='日期/收盘/范围三类证据独立；请求日、qdate或抓取时间不单独充当行情日期'
    return meta


def normalize_frame(frame, *, listing_dates=None, source_meta=None, master_identities=None):
    if frame is None or not hasattr(frame,'columns'):return []
    listing_dates=listing_dates or {};meta=source_meta or {};master_identities=master_identities or {}
    fields={
      'code':['代码','股票代码','证券代码','code','symbol'], 'name':['名称','股票名称','证券简称','name'],
      'board':['连板数','昨日连板数','连续涨停天数','board'],
      'listing_date':['上市日期','A股上市日期','listing_date'],
      'change_pct':['涨跌幅','涨幅','change_pct'], 'open':['今开','开盘','开盘价','open'],
      'close':['最新价','收盘','收盘价','close'], 'limit_up_price':['涨停价','limit_up_price'],
      'limit_down_price':['跌停价','limit_down_price'],
      'amount':['成交额','成交金额','amount'],
      'seal_time':['首次封板时间','seal_time'], 'last_seal_time':['最后封板时间','last_seal_time'],
      'seal_amount':['封板资金','seal_amount'], 'turnover':['换手率','turnover'],
      'open_count':['炸板次数','open_count'], 'float_mv':['流通市值','float_mv'],
      'industry':['所属行业','industry'], 'limit_up_reason':['涨停原因','limit_up_reason'],
    }
    cols={k:find_column(frame,v) for k,v in fields.items()}
    actual_date_col=find_column(frame,['source_date','日期','交易日期','trade_date'])
    output=[]
    for _,r in frame.iterrows():
        row={k:r.get(c) if c else None for k,c in cols.items()};code=normalize_code(row['code']);row['code']=code
        row['listing_date']=day(row.get('listing_date')) or listing_dates.get(code)
        identity=master_identities.get(code)
        # Master identifies security/board, NOT the quote date or pool coverage.
        if identity:
            row['market_board']=identity.get('market_board') if identity.get('market_board')!='UNKNOWN' else r.get('market_board')
            row['market_board_evidence']=dict(identity)
            if identity.get('listing_date_conflict'):
                row['listing_date']=None
        elif isinstance(r.get('market_board'),str):
            row['market_board']=r.get('market_board')
            row['market_board_evidence']=r.get('market_board_evidence')

        # Row date must be actual metadata, never observation label alone.
        row['source_date']=day(r.get(actual_date_col)) if actual_date_col else None
        row['source_date']=row['source_date'] or (meta.get('source_date') if meta.get('date_verified') is True else None)
        row['as_of']=r.get('as_of',meta.get('as_of'))
        row['board']=board_count(row['board'])
        for key in ['change_pct','open','close','limit_up_price','limit_down_price','amount','seal_amount','turnover','float_mv']:
            row[key]=number(row[key])
        row['open_count']=integer(row['open_count'],minimum=0)
        for key in ['is_st','is_limit_up','is_limit_down','touched_limit_up','open_at_limit','suspended']:
            row[key]=boolean(r.get(key))
        # Exact price comparisons only if authoritative daily limit prices supplied.
        if row['is_limit_up'] is None and row['close'] is not None and row['limit_up_price'] is not None:
            row['is_limit_up']=row['close']==row['limit_up_price']
        if row['is_limit_down'] is None and row['close'] is not None and row['limit_down_price'] is not None:
            row['is_limit_down']=row['close']==row['limit_down_price']
        output.append(row)
    return output


def parse_ths_883900(payload, observation):
    """Only accept explicit identity/date/percent fields. Never derive from index level."""
    result={'code':'883900','source':'THS_883900','status':'IDENTITY_UNVERIFIED','value':None,
            'unit':'%','identity_verified':False,'date_verified':False,'source_date':None}
    candidates=[]
    def walk(obj, parent_key=''):
        if isinstance(obj,dict):
            candidate=dict(obj)
            if parent_key in ('883900','bk_883900'):candidate.setdefault('code','883900')
            candidates.append(candidate)
            for k,v in obj.items():walk(v,str(k))
        elif isinstance(obj,list):
            for v in obj:walk(v,parent_key)
    walk(payload)
    for obj in candidates:
        code=str(obj.get('code',obj.get('symbol',obj.get('代码','')))).replace('bk_','')
        if code!='883900':continue
        result['identity_verified']=True
        raw_date=obj.get('date',obj.get('trade_date',obj.get('日期',obj.get('source_date'))))
        d=day(raw_date);result['source_date']=d;result['date_verified']=d==day(observation) and d is not None
        if not result['date_verified']:
            result['status']='DATE_UNVERIFIED_OR_MISMATCH';continue
        for field in ('change_pct','pct_chg','涨跌幅'):
            if field not in obj:continue
            val=number(obj[field])
            if val is None:
                result['status']='INVALID_VALUE';continue
            # These named fields must be percentage points, not fraction/price.
            if obj.get('unit')!='%':result['status']='UNIT_UNVERIFIED';continue
            return {**result,'status':'VALID','value':val,'source_field':field,
                    'as_of':obj.get('as_of'),'provider_payload':obj}
    return result


def fetch_ths_883900(observation, previous_date=None, *, supplier=None, session=None, timeout=8):
    try:
        if supplier is not None:
            raw=supplier('883900',observation)
        else:
            if previous_date is None:
                raise ValueError('previous trading date is required for 883900 historical return')
            from collection.fuyao_provider import historical_883900
            return historical_883900(observation, previous_date, session=session, timeout=timeout)
        return parse_ths_883900(raw,observation)
    except Exception as exc:
        return {'code':'883900','status':'ERROR','value':None,'identity_verified':False,'date_verified':False,
                'source_date':None,'unit':'%','error':str(exc),'error_type':type(exc).__name__}


def build_master_identity(masters):
    """Index existing exchange-master responses; no price/date calibration.

    `masters` is [(DataFrame, provenance dict)], retaining exact consumed rows.
    Conflicting identities never become an arbitrary last-row-wins assignment.
    A new trading code does not reset the supplied original listing date.
    """
    identities, captures = {}, []
    for frame, provenance in masters:
        if not isinstance(frame, pd.DataFrame):
            continue
        cc=find_column(frame,['代码','证券代码','A股代码','code'])
        lc=find_column(frame,['上市日期','A股上市日期','listing_date'])
        bc=find_column(frame,['market_board','板块'])
        rows=clean_json(frame.astype(object).where(pd.notna(frame),None).values.tolist())
        encoded=json.dumps({'columns':[str(c) for c in frame.columns],'data':rows},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
        capture={'source':dict(provenance),'columns':[str(c) for c in frame.columns],
                 'data':rows,'normalized_table_sha256':hashlib.sha256(encoded).hexdigest(),
                 'layer':'EXCHANGE_MASTER_POST_AKSHARE_NOT_RAW_HTTP',
                 'quote_date_proof':False,'quote_completeness_proof':False}
        captures.append(capture)
        if not cc: continue
        symbol=provenance.get('args',{}).get('symbol')
        interface=provenance.get('interface')
        for idx,(_,row) in enumerate(frame.iterrows()):
            code=normalize_code(row.get(cc))
            if not code: continue
            raw_board=row.get(bc) if bc else None
            board=raw_board if isinstance(raw_board,str) and raw_board in ('SSE_MAIN_A','SZSE_MAIN_A','CHINEXT_A','STAR_A') else None
            if interface=='stock_info_sh_name_code':
                board={'主板A股':'SSE_MAIN_A','科创板':'STAR_A'}.get(symbol)
            elif interface=='stock_info_sz_name_code' and symbol=='A股列表':
                board={'主板':'SZSE_MAIN_A','创业板':'CHINEXT_A'}.get(str(raw_board).strip())
            # For explicitly injected masters require an explicit recognized label;
            # generic 主板 without known exchange is not silently classified.
            old=identities.get(code)
            listing=day(row.get(lc)) if lc else None
            entry={'code':code,'market_board':board or 'UNKNOWN','listing_date':listing,
                   'source':dict(provenance),'source_table_sha256':capture['normalized_table_sha256'],
                   'source_row':idx,'raw_board':clean_json(raw_board),
                   'quote_date_proof':False,'historical_identity_mapping':'NOT_INFERRED'}
            if old:
                known={x for x in (old.get('market_board'),entry['market_board']) if x!='UNKNOWN'}
                dates={x for x in (old.get('listing_date'),listing) if x is not None}
                if len(known)>1 or 'CONFLICT' in known:
                    entry['market_board']='CONFLICT';entry['identity_conflict']=True
                elif known:entry['market_board']=next(iter(known))
                if len(dates)>1 or old.get('listing_date_conflict'):
                    entry['listing_date']=None;entry['listing_date_conflict']=True
                elif dates:entry['listing_date']=next(iter(dates))
                entry['multiple_source_rows']=True
            identities[code]=entry
    return identities,captures


def enrich_existing_data(data, *, ak_client=None, source_meta=None, calendar=None, master=None, primary_supplier=None, candidate_validation_supplier=None, validation_policy=None):
    """Works with existing DashboardData. Fixture callers inject sources; no production mocks."""
    diagnostics=[]
    if ak_client is None:
        try:import akshare as ak_client
        except ImportError as exc:diagnostics.append({'interface':'akshare','status':'DEPENDENCY_MISSING','error':str(exc)})
    cal_meta={'verified':False,'source':'akshare.tool_trade_date_hist_sina','dates':[]}
    if isinstance(calendar,dict):cal_meta=calendar
    elif ak_client is not None:
        try:
            cf=ak_client.tool_trade_date_hist_sina();col=find_column(cf,['trade_date','日期'])
            dates=[day(x) for x in cf[col]] if col else []
            cal_meta={'verified':day(data.date) in dates,'source':'akshare.tool_trade_date_hist_sina','dates':dates}
        except Exception as exc:diagnostics.append({'interface':'tool_trade_date_hist_sina','status':'ERROR','error':str(exc)})
    if master is not None:
        masters=[(master,{'interface':'EXPLICIT_MASTER_INPUT','args':{}})]
    elif ak_client is not None:
        masters=[]
        for fn,args in [('stock_info_sh_name_code',{'symbol':'主板A股'}),('stock_info_sh_name_code',{'symbol':'科创板'}),('stock_info_sz_name_code',{'symbol':'A股列表'})]:
            try:
                masters.append((getattr(ak_client,fn)(**args),{'interface':fn,'args':dict(args)}))
            except Exception as exc:
                diagnostics.append({'interface':fn,'args':args,'status':'ERROR','error':str(exc)})
    else:masters=[]
    identities,master_captures=build_master_identity(masters)
    listings={code:r.get('listing_date') for code,r in identities.items()}
    # User-approved batch close proof: complete after-close Sina spot collection
    # establishes the market batch date/finality without per-stock daily requests.
    # Existing Eastmoney event pools use their requested-date transport contract.
    from evidence.batch_close_evidence import apply_batch_close_proofs
    batch_close_evidence=apply_batch_close_proofs(data,cal_meta)
    frames={n:getattr(data,n,None) for n in ('market','limit_up','limit_down','open_board','previous_limit_up','previous_pool_performance')}
    meta={n:receipt(f,data.previous_date if n=='previous_limit_up' else data.date,n) for n,f in frames.items()}
    meta.update(source_meta or {})
    from collection.market_breadth_legu import MODE
    if getattr(data, 'collection_mode', None) == MODE:
        from pool_scoped_runtime import build_bundle
        return build_bundle(data, cal_meta, identities, master_captures, meta,
            batch_close_evidence, diagnostics, candidate_supplier=candidate_validation_supplier,
            validation_policy=validation_policy, primary_supplier=primary_supplier)
    today=normalize_frame(frames['market'],listing_dates=listings,master_identities=identities,source_meta=meta['market'])
    tm={r['code']:r for r in today}
    # Only date-verified closed pools are authoritative positive membership.
    for field,flag in [('limit_up','is_limit_up'),('limit_down','is_limit_down'),('open_board','touched_limit_up')]:
        rows=normalize_frame(frames[field],listing_dates=listings,master_identities=identities,source_meta=meta[field])
        if not meta[field].get('date_verified'):continue
        members={r['code'] for r in rows}
        for code,row in tm.items():
            if code in members:row[flag]=True
            elif meta[field].get('complete') is True:row[flag]=False
        for row in rows:
            code=row['code'];row[flag]=True
            if code not in tm:tm[code]=row
            elif field=='limit_up':
                for key in ('board','seal_time','last_seal_time','seal_amount','turnover','open_count','amount','float_mv','industry','limit_up_reason'):
                    if row.get(key) is not None:tm[code][key]=row[key]
                if row.get('is_limit_up') is True:tm[code]['touched_limit_up']=True
    # A closed limit-up necessarily touched its limit even when the complete
    # open-board pool says it was not an *open-board failure*.
    for row in tm.values():
        if row.get('is_limit_up') is True:
            row['touched_limit_up']=True
            row['is_limit_down']=False

    # Previous-performance pool supplies today's returns for yesterday members,
    # not yesterday membership. Preserve this date distinction.
    perf=normalize_frame(frames['previous_pool_performance'],listing_dates=listings,master_identities=identities,source_meta=meta['previous_pool_performance'])
    for row in perf:
        if row['code'] in tm and row['source_date']==day(data.date) and tm[row['code']].get('change_pct') is None:
            tm[row['code']]['change_pct']=row['change_pct']
    prior=normalize_frame(frames['previous_limit_up'],listing_dates=listings,master_identities=identities,source_meta=meta['previous_limit_up'])
    if meta['previous_limit_up'].get('date_verified'):
        for row in prior:row['is_limit_up']=True
    # Explicit opt-in supplements existing provider evidence, never overwrites any
    # original price, source table, market-level date, or pool completeness.
    try:
        from evidence.candidate_quote_evidence import collect_candidates
        candidate_proofs=collect_candidates(data,identities,cal_meta,policy=validation_policy,
                                            fetch=candidate_validation_supplier)
    except Exception as exc:
        candidate_proofs={'status':'ERROR','records':{},'requests':{},
                          'error':str(exc),'price_replacement':False,'full_market_proven':False}
    prior_map={r['code']:r for r in prior}
    for code,proof in candidate_proofs.get('records',{}).items():
        if proof.get('status')!='VALID':continue
        from evidence.candidate_quote_evidence import cents
        target_current=tm.get(code)
        pc=proof.get('current') or {}
        if target_current is not None and (cents(target_current.get('close'))!=cents(pc.get('daily_close'))
            or (target_current.get('open') is not None and cents(target_current.get('open'))!=cents(pc.get('daily_open')))):
            proof.update(status='DATA_PENDING',date_verified=False,closing_verified=False,
                         issues=list(proof.get('issues',[]))+['ORIGINAL_MARKET_AND_DATED_POOL_PRICE_CONFLICT'])
            proof['current']={**pc,'status':'DATA_PENDING','date_verified':False,'closing_verified':False}
            continue
        for which,target in [('current',target_current),('previous',prior_map.get(code))]:
            detail=proof.get(which) or {}
            if target is None or detail.get('status')!='VALID':continue
            # Dates and Boolean states are derived from captured same-provider
            # evidence. Missing open is kept missing; no price is copied over.
            target['source_date']=detail['source_date']
            target['date_verified']=True;target['closing_verified']=True
            target['is_limit_up']=detail['close_limit_up']
            target['open_at_limit']=detail['open_at_limit_up']
            target['individual_quote_evidence']={'method':proof['method'],'available_at':proof.get('available_at'),
                                                'proof_pointer':'/candidate_quote_evidence/records/'+code+'/'+which}
    candidate_proofs['validated_candidates']=sum(x.get('status')=='VALID' for x in candidate_proofs.get('records',{}).values())
    primary=fetch_ths_883900(data.date,data.previous_date,supplier=primary_supplier)
    bundle={'date':data.date,'previous_date':data.previous_date,'calendar':cal_meta,
            'previous_records':prior,'today_records':list(tm.values()),'primary_883900':primary,
            'source_meta':{'today':meta['market'],'previous':meta['previous_limit_up']},
            'acquisition_receipts':meta,'diagnostics':diagnostics,'security_master_inputs':master_captures,
            'candidate_quote_evidence':candidate_proofs,'batch_close_evidence':batch_close_evidence,
            'security_master_identity_summary':{'resolved':sum(v['market_board'] not in ('UNKNOWN','CONFLICT') for v in identities.values()),'unknown':sum(v['market_board']=='UNKNOWN' for v in identities.values()),'conflicts':[c for c,v in identities.items() if v.get('identity_conflict') or v.get('listing_date_conflict')]}}
    data.input_kind=getattr(data,'input_kind','LIVE_SOURCE_DATE_NOT_AUTOMATICALLY_VERIFIED')
    bundle['input_kind']=data.input_kind
    bundle['frame_inputs']=capture_frame_inputs(data)
    bundle['frame_capture_layer']='POST_EXISTING_FETCHER_BEFORE_APPROVED_POLICY_NOT_HTTP_RESPONSE'
    from evidence.public_metric_evidence import apply_to_bundle
    apply_to_bundle(bundle)
    bundle['source_evidence_gaps']=[{'interface':name,'status':m.get('status'),
        'missing':[key for key in ('source_date','as_of') if not m.get(key)]+([] if m.get('complete') is True else ['completeness_proof'])}
        for name,m in meta.items() if not m.get('date_verified') or not m.get('complete')]
    data.policy_bundle=bundle
    return bundle


def data_from_bundle(bundle):
    """Replay a saved REAL or explicitly SYNTHETIC input through the original pipeline."""
    def frame(rows):
        rec=[]
        for r in rows:
            item=dict(r)
            names={'code':'代码','name':'名称','board':'连板数','change_pct':'涨跌幅','close':'最新价',
                   'open':'今开','seal_time':'首次封板时间','last_seal_time':'最后封板时间',
                   'seal_amount':'封板资金','turnover':'换手率','open_count':'炸板次数','amount':'成交额',
                   'float_mv':'流通市值','industry':'所属行业','limit_up_reason':'涨停原因'}
            item.update({cn:r.get(en) for en,cn in names.items()});rec.append(item)
        # Empty frames retain contract columns; actual no rows != unknown evidence.
        return pd.DataFrame(rec) if rec else pd.DataFrame(columns=['代码','名称','连板数','涨跌幅'])
    today=bundle.get('today_records',[]);prior=bundle.get('previous_records',[])
    restored = bundle.get('frame_inputs')
    if isinstance(restored, dict):
        missing = [name for name in FRAME_NAMES if name not in restored]
        if missing:
            raise ValueError('Partial captured frame set; missing: ' + ','.join(missing))
        values = {name: _restore_frame(restored[name]) for name in FRAME_NAMES}
        replay_fidelity = 'CAPTURED_POST_FETCHER_FRAMES_RESTORED'
    else:
        values = {'market':frame(today),
            'limit_up':frame([r for r in today if boolean(r.get('is_limit_up')) is True]),
            'limit_down':frame([r for r in today if boolean(r.get('is_limit_down')) is True]),
            'open_board':frame([r for r in today if boolean(r.get('touched_limit_up')) is True and boolean(r.get('is_limit_up')) is False]),
            'previous_limit_up':frame(prior),'previous_pool_performance':frame(today)}
        replay_fidelity = 'NORMALIZED_ONLY_RAW_POOL_RECONSTRUCTION_NOT_PROVEN'
    return SimpleNamespace(date=bundle['date'],previous_date=bundle['previous_date'],policy_bundle=bundle,
        input_kind=bundle.get('input_kind','FROZEN_INPUT_UNCLASSIFIED'),
        replay_fidelity=replay_fidelity, collection_mode=bundle.get('collection_mode'),
        market_breadth_raw=(bundle.get('market_breadth') or {}).get('raw'), **values)
