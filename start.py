# -*- coding: utf-8 -*-
"""5535 repaired original pipeline. No new website, ledger or live strategy.

Live: python start.py
Frozen replay: python start.py --input <approved_bundle.json> --output-dir <isolated-dir>
No generated test snapshot should be installed as production data.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import hashlib
import json
import traceback
from types import SimpleNamespace
from core.input_contracts import clean_json

VERSION='5535-direct-repair-1'

def _fund_cycle_position(data, bundle, smash, emotion):
    """Build displayed cycle and position from persisted money5 facts."""
    from types import SimpleNamespace
    try:
        from market_speed_883900 import storage
        from market_speed_883900.money_view import make_view
        from pathlib import Path
        db = Path(__file__).resolve().parent / 'data' / '.migration_shadow' / 'market_store_5535.next.sqlite3'
        if not storage.active(db):
            raise ValueError('MONEY5_INDEX_NOT_ACTIVE')
        calendar = (bundle.get('calendar') or {}).get('dates', [])
        view = make_view(calendar, storage.daily_rows(db), str(data.date).replace('-', ''))
        current = view.get('current') or {}
        fund = current.get('fund_cycle')
        stage = current.get('stage')
        if current.get('status') != 'VALID' or fund is None or not stage:
            return (SimpleNamespace(emotion_cycle=None, height_cycle=None, comprehensive=None,
                                    stage=None, trend=None, description='五日资金周期尚未形成完整五交易日证据。',
                                    status='DATA_PENDING'),
                    {'status': 'DATA_PENDING', 'suggest': None, 'risk': None,
                     'strategy': '五日资金周期数据不足，暂不生成仓位建议。',
                     'source': 'MONEY5_FACT_V2', 'fund_cycle': fund})
        stage_map = {'深度反击': '退潮阶段', '启动进攻': '弱修复阶段',
                     '均衡参与': '修复阶段', '动能减弱': '活跃阶段',
                     '防御减仓': '弱修复阶段', '退潮警戒': '退潮阶段',
                     '脉冲尾声': '高潮阶段'}
        position_stage = stage_map.get(stage, '修复阶段')
        cycle = SimpleNamespace(emotion_cycle=stage, height_cycle=stage,
                                comprehensive=stage, stage=position_stage, trend=None,
                                description=f'资金周期 {fund:.2f}% · {stage}（T-4前收盘至T收盘）',
                                status='VALID', fund_cycle=fund, fund_cycle_stage=stage)
        from analytics.position_engine import calculate_position
        position = calculate_position(cycle, smash, emotion)
        position.update(status='VALID', source='MONEY5_FACT_V2', fund_cycle=fund,
                        fund_cycle_stage=stage)
        return cycle, position
    except Exception as exc:
        return (SimpleNamespace(emotion_cycle=None, height_cycle=None, comprehensive=None,
                                stage=None, trend=None, description='五日资金周期读取失败，暂不生成仓位建议。',
                                status='DATA_PENDING'),
                {'status': 'DATA_PENDING', 'suggest': None, 'risk': None,
                 'strategy': '五日资金周期读取失败，暂不生成仓位建议。',
                 'source': 'MONEY5_FACT_V2', 'error': type(exc).__name__ + ': ' + str(exc)})


def run_pipeline(data, *, policy_bundle=None, output_dir=None, persist_history=False,
                 build_text_report=False, archive_only=False, progress_callback=None):
    def step(step_id, label, state):
        if progress_callback:
            progress_callback(step_id, label, state)
    from market_pipeline import apply_context
    from analytics.cycle_engine import analyze_cycle
    import dashboard_snapshot
    warnings=[]
    bundle=policy_bundle or getattr(data,'policy_bundle',None)
    if bundle is None:
        from core.approved_data_adapter import enrich_existing_data
        bundle=enrich_existing_data(data)
    # Save all consumed post-fetcher frames before apply_context filters them.
    # Normalized rows alone cannot reproduce unknown-date legacy candidates.
    from core.approved_data_adapter import capture_frame_inputs
    bundle=dict(bundle)
    bundle.setdefault('input_kind',getattr(data,'input_kind','UNCLASSIFIED'))
    if 'frame_inputs' not in bundle:
        bundle['frame_inputs']=capture_frame_inputs(data)
        bundle['frame_capture_layer']='POST_EXISTING_FETCHER_BEFORE_APPROVED_POLICY_NOT_HTTP_RESPONSE'
    data.policy_bundle=bundle
    replay_fidelity=getattr(data,'replay_fidelity','LIVE_POST_FETCHER_CAPTURE')
    if replay_fidelity=='NORMALIZED_ONLY_RAW_POOL_RECONSTRUCTION_NOT_PROVEN' and not str(bundle.get('input_kind','')).startswith('SYNTHETIC'):
        warnings.append({'component':'replay_fidelity','status':'PARTIAL',
            'reason':'旧输入缺原始返回表，不能证明完整候选/可选模块重放一致；本次捕获不反向补造旧表'})
    step('policy_filter', '应用范围与过滤规则', 'RUNNING')
    context=apply_context(data,bundle)
    step('policy_filter', '应用范围与过滤规则', 'DONE')
    # Keep only the validated aggregate needed by the UI.  The provider's
    # raw response remains evidence, while this narrow fact supports historical
    # reads without reloading a full market payload into every snapshot.
    try:
        step('breadth_fact', '保存市场宽度事实', 'RUNNING')
        from collection.market_breadth_store import upsert as upsert_market_breadth
        breadth_db = Path(__file__).resolve().parent / 'data' / '.migration_shadow' / 'market_store_5535.next.sqlite3'
        upsert_market_breadth(breadth_db, {
            **(context.get('breadth') or {}),
            'trade_date': data.date,
            'source': (context.get('breadth') or {}).get('source') or 'LEGULEGU',
            'source_date': (context.get('breadth') or {}).get('source_date') or data.date,
        })
        step('breadth_fact', '保存市场宽度事实', 'DONE')
    except Exception as exc:
        step('breadth_fact', '保存市场宽度事实', 'SKIPPED')
        warnings.append({'component':'market_breadth_daily','status':'ERROR','error':str(exc)})
    from analytics.independent_modules import calculate_independent_modules, save_independent_history
    step('smash', '计算砸盘情绪', 'RUNNING')
    step('emotion', '计算市场情绪', 'RUNNING')
    smash, emotion, module_status = calculate_independent_modules(data, context)
    step('smash', '计算砸盘情绪', 'DONE')
    step('emotion', '计算市场情绪', 'DONE')
    data.module_status = module_status
    # Separate SQL metrics on next normal ingest; no old batch rewrite.
    context['smash_module']={'value':smash.score,'status':module_status['smash']['status'],
        'date':data.date,'depends_on_emotion_score':False,
        'detail':getattr(smash,'smash_detail',{})}
    context['emotion_module']={'value':emotion.score,'status':module_status['emotion']['status'],
        'date':data.date,'depends_on_smash_score':False,
        'detail':getattr(emotion,'detail',{})}
    warnings.extend([{'component':k,'status':v['status'],'error':v.get('error')}
                     for k,v in module_status.items() if v['status']=='ERROR'])
    history=[]
    data.history_write_status={'emotion':'NOT_REQUESTED','smash':'NOT_REQUESTED'}
    if persist_history:
        step('history', '保存独立历史事实', 'RUNNING')
        history, data.history_write_status, history_warnings = save_independent_history(
            data, context, smash, emotion, module_status)
        warnings.extend(history_warnings)
        step('history', '保存独立历史事实', 'DONE')
    else:
        step('history', '保存独立历史事实', 'SKIPPED')
    step('cycle', '计算情绪周期', 'RUNNING')
    cycle, position = _fund_cycle_position(data, bundle, smash, emotion)
    step('cycle', '计算情绪周期', 'DONE')
    step('position', '计算仓位建议', 'DONE')
    # Isolated replay targets do not touch real history or production snapshot.
    old_file,old_dir=dashboard_snapshot.DATA_FILE,dashboard_snapshot.SNAPSHOT_DIR
    actual_output = None
    try:
        step('snapshot', '生成仪表盘快照', 'RUNNING')
        if output_dir:
            out=Path(output_dir);dashboard_snapshot.DATA_FILE=out/'dashboard.json';dashboard_snapshot.SNAPSHOT_DIR=out/'history'
        result=dashboard_snapshot.save_dashboard_snapshot(
            data, smash, emotion, cycle, position, archive_only=archive_only
        )
        actual_output = (
            dashboard_snapshot.SNAPSHOT_DIR / f"{result['date']}.json"
            if archive_only else dashboard_snapshot.DATA_FILE
        )
        step('snapshot', '生成仪表盘快照', 'DONE')
    finally:
        dashboard_snapshot.DATA_FILE, dashboard_snapshot.SNAPSHOT_DIR=old_file,old_dir
    if build_text_report and bundle.get('collection_mode') == 'POOL_SCOPED_WITH_LEGU_NATIVE':
        warnings.append({'component':'legacy_text_report','status':'SKIPPED',
            'reason':'旧文字报告依赖全市场逐股表；新模式使用SQLite每日研究报告，不以核心池冒充宽度'})
    if build_text_report and bundle.get('collection_mode') != 'POOL_SCOPED_WITH_LEGU_NATIVE':
        try:
            from reports.report_builder import build_report
            build_report(version=VERSION,date=data.date,previous_date=data.previous_date,
                market=data.market,limit_up=data.limit_up,limit_down=data.limit_down,open_board=data.open_board,
                smash=smash,emotion=emotion,cycle=cycle,position=position)
        except Exception as exc:
            warnings.append({'component':'existing_report_builder','status':'ERROR','error':str(exc)})
    manifest={'version':VERSION,'input_kind':getattr(data,'input_kind','UNCLASSIFIED'),
        'runtime_scope':'ORIGINAL_PIPELINE_COMPUTED_OUTPUT_NOT_SOURCE_DATE_OR_WEB_ACCEPTANCE',
        'source_imports':{},'replay_fidelity':replay_fidelity,'runtime_warnings':warnings,'input_sha256':hashlib.sha256(json.dumps(clean_json(bundle),sort_keys=True,ensure_ascii=False).encode()).hexdigest()}
    import sys
    for name in ('start','collection.market_breadth_legu','pool_scoped_runtime','evidence.batch_close_evidence','core.approved_data_adapter','evidence.candidate_quote_evidence','evidence.public_metric_evidence','analytics.independent_modules','core.input_contracts','collection.source_transport','collection.data_fetcher','market_pipeline','analytics.smash_dynamic','core.approved_policy','scoring.three_board_model','scoring.data_quality','dashboard_snapshot','analytics.cycle_engine','analytics.smash_engine','analytics.emotion_engine'):
        module=sys.modules.get(name) or (sys.modules.get('__main__') if name=='start' else None)
        file=getattr(module,'__file__',None)
        if file and Path(file).is_file():
            manifest['source_imports'][name]={'path':str(Path(file).resolve()),'sha256':hashlib.sha256(Path(file).read_bytes()).hexdigest()}
    # One latest-run evidence set, not an expanding research ledger.
    out = Path(output_dir) if output_dir else dashboard_snapshot.DATA_FILE.parent/'last_generation'
    out.mkdir(parents=True, exist_ok=True)
    def atomic_write(path, text):
        tmp=path.with_name(path.name+'.tmp')
        tmp.write_text(text,encoding='utf-8')
        tmp.replace(path)
    step('generation_manifest', '写入生成清单与哈希', 'RUNNING')
    atomic_write(out/'input.json',json.dumps(clean_json(bundle),ensure_ascii=False,indent=2,allow_nan=False))
    if actual_output is None:
        raise RuntimeError('DASHBOARD_SNAPSHOT_NOT_WRITTEN')
    if not output_dir:
        # Byte-for-byte last generation evidence, never overwrites dated history.
        temp=out/'dashboard.json.tmp';temp.write_bytes(actual_output.read_bytes());temp.replace(out/'dashboard.json')
    manifest['saved_input_file_sha256']=hashlib.sha256((out/'input.json').read_bytes()).hexdigest()
    manifest['output_sha256']=hashlib.sha256(actual_output.read_bytes()).hexdigest()
    manifest['output_path']=str(actual_output.resolve())
    manifest['frame_capture_layer']=bundle.get('frame_capture_layer')
    atomic_write(out/'generation_manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2,allow_nan=False))
    step('generation_manifest', '写入生成清单与哈希', 'DONE')
    for warning in warnings:print('INTEGRATION_WARNING',json.dumps(warning,ensure_ascii=False))
    return result,manifest


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path);parser.add_argument('--output-dir',type=Path)
    args=parser.parse_args()
    if args.input:
        if not args.output_dir:parser.error('--input replay requires --output-dir to protect live data')
        from core.approved_data_adapter import data_from_bundle
        bundle=json.loads(args.input.read_text(encoding='utf-8'));data=data_from_bundle(bundle)
        run_pipeline(data,policy_bundle=bundle,output_dir=args.output_dir)
    else:
        from collection.data_fetcher import fetch_dashboard_data
        data=fetch_dashboard_data()
        run_pipeline(data,output_dir=args.output_dir,persist_history=args.output_dir is None,build_text_report=args.output_dir is None)

if __name__=='__main__':main()
