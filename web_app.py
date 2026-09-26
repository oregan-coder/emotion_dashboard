# -*- coding: utf-8 -*-

"""
============================================================
A股打板情绪仪表盘 V3.1.1
本地 Web 服务（展示层）

启动：
    python web_app.py

访问：
    http://127.0.0.1:5000

接口：
    /                       仪表盘页面
    /api/dashboard          今日仪表盘数据（JSON）
    /api/dashboard?date=    指定交易日快照（回放）
    /api/dates              可用回放交易日列表
    /api/history            完整历史数据（JSON，供回测/趋势使用）
============================================================
"""

import json
import re
import hashlib
import sqlite3
import uuid
import calendar
from snapshot_loader import SnapshotConfig, load_validation_data, get_config
from cycle_theme_view import load_cycle_theme_data
from evidence.evidence_ledger import build_ledger_view, SCHEMA_VERSION as LEDGER_SCHEMA_VERSION, LedgerRootError
import threading
import subprocess
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta

from flask import Flask, render_template, jsonify, request

from dashboard_data import build_dashboard, _clean, load_smash_history

from storage.history_manager import load_history

def _attach_money_cycle_position(snapshot):
    """Read-only presentation adapter for persisted money5 position advice."""
    if not isinstance(snapshot, dict):
        return snapshot
    try:
        from types import SimpleNamespace
        from market_speed_883900 import storage
        from market_speed_883900.money_view import make_view
        from analytics.position_engine import calculate_position
        db_path = Path(__file__).resolve().parent / 'data' / '.migration_shadow' / 'market_store_5535.next.sqlite3'
        if not storage.active(db_path):
            return snapshot
        records = storage.daily_rows(db_path)
        date = str(snapshot.get('date') or '').replace('-', '')
        if not date or date not in records:
            return snapshot
        view = make_view(sorted(records), records, date)
        current = view.get('current') or {}
        fund, stage = current.get('fund_cycle'), current.get('stage')
        if current.get('status') != 'VALID' or fund is None or not stage:
            return snapshot
        stage_map = {'深度反击': '退潮阶段', '启动进攻': '弱修复阶段', '均衡参与': '修复阶段',
                     '动能减弱': '活跃阶段', '防御减仓': '弱修复阶段',
                     '退潮警戒': '退潮阶段', '脉冲尾声': '高潮阶段'}
        cycle_stage = stage_map.get(stage, '修复阶段')
        cycle = SimpleNamespace(stage=cycle_stage, fund_cycle_stage=stage,
                                comprehensive=stage, emotion_cycle=stage, height_cycle=stage,
                                description=f'资金周期 {fund:.2f}% · {stage}（T-4前收盘至T收盘）')
        existing = dict(snapshot.get('position') or {})
        # Always rebuild the display recommendation from the persisted money
        # cycle. Existing snapshots may contain a legacy coarse mapping (for
        # example 20%-30% for 防御减仓); retaining it would make the same fact
        # render differently across dates and update/backfill paths.
        position = calculate_position(cycle, snapshot.get('smash') or {}, snapshot.get('emotion') or {})
        position.update(status='VALID', source='MONEY5_FACT_V2', fund_cycle=fund,
                        fund_cycle_stage=stage)
        existing = {**existing, **position}
        # `suggest` is the legacy field consumed by the card UI; keep it in
        # lockstep with the canonical position label even when an old snapshot
        # already had a stale recommendation.
        if existing.get('position'):
            existing['suggest'] = existing['position']
        snapshot['position'] = existing
        snapshot['cycle'] = {**(snapshot.get('cycle') or {}), 'status': 'VALID',
                             'stage': cycle_stage, 'comprehensive': stage,
                             'fund_cycle': fund, 'fund_cycle_stage': stage,
                             'description': cycle.description}
    except Exception:
        return snapshot
    return snapshot


def _attach_market_breadth_fact(snapshot):
    """Overlay a validated narrow breadth fact on a historical snapshot."""
    if not isinstance(snapshot, dict):
        return snapshot
    date = str(snapshot.get('date') or '').replace('-', '')
    if not re.fullmatch(r'\d{8}', date):
        return snapshot
    try:
        from collection.market_breadth_store import read as read_market_breadth
        fact = read_market_breadth(_UPDATE_DB, date)
        if not fact or fact.get('status') != 'VALID':
            return snapshot
        market = dict(snapshot.get('market') or {})
        market.update({
            'status': 'VALID', 'complete': True,
            'up': fact.get('up_count'), 'down': fact.get('down_count'),
            'flat': fact.get('flat_count'), 'unknown': fact.get('unknown_count', 0),
            'source': fact.get('source') or market.get('source') or 'LEGULEGU',
            'source_date': fact.get('source_date') or date,
            'as_of': fact.get('as_of'),
            'date_verified': True, 'closing_verified': True,
            'request_status': 'PERSISTED_VALIDATED_FACT',
            'issues': [], 'market_breadth_fact_source': 'market_breadth_daily',
        })
        snapshot['market'] = market
        evidence = dict(snapshot.get('input_evidence') or {})
        evidence['breadth'] = {
            'status': 'VALID', 'up': fact.get('up_count'),
            'down': fact.get('down_count'), 'flat': fact.get('flat_count'),
            'unknown': fact.get('unknown_count', 0),
            'source': fact.get('source') or 'LEGULEGU',
            'source_date': fact.get('source_date') or date,
            'as_of': fact.get('as_of'),
            'read_source': 'market_breadth_daily',
        }
        snapshot['input_evidence'] = evidence
    except Exception:
        return snapshot
    return snapshot


def _overlay_market_breadth_score(snapshot):
    """Restore a matched same-day breadth score without fabricating counts."""
    if not isinstance(snapshot, dict):
        return snapshot
    date = str(snapshot.get('date') or '').replace('-', '')
    batch_id = str(snapshot.get('published_batch_id') or '')
    if not re.fullmatch(r'\d{8}', date) or not batch_id:
        return snapshot
    db = None
    try:
        db = sqlite3.connect(f'file:{_UPDATE_DB.as_posix()}?mode=ro', uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        gate = db.execute(
            "SELECT 1 FROM fact_read_gate WHERE family='market_breadth' AND trade_date=? "
            "AND source_batch_id=? AND status='MATCH'", (date, batch_id)).fetchone()
        row = db.execute(
            "SELECT value_real,status FROM market_metrics_fact WHERE trade_date=? "
            "AND metric='breadth' AND source_batch_id=?", (date, batch_id)).fetchone()
        if not gate or not row or row['status'] != 'VALID' or row['value_real'] is None:
            return snapshot
        emotion = snapshot.get('emotion')
        detail = emotion.get('detail') if isinstance(emotion, dict) else None
        if not isinstance(detail, dict):
            return snapshot
        detail = dict(detail)
        detail['市场宽度'] = float(row['value_real'])
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool)
                   for value in detail.values()):
            return snapshot
        emotion = dict(emotion)
        emotion['detail'] = detail
        emotion['missing_fields'] = [item for item in (emotion.get('missing_fields') or [])
                                     if item != '市场宽度']
        emotion['status'] = 'VALID'
        emotion['score'] = round(sum(float(value) for value in detail.values()), 2)
        cycle = snapshot.get('cycle') or {}
        if emotion.get('cycle_stage') in (None, '', '待证据') and cycle.get('fund_cycle_stage'):
            emotion['cycle_stage'] = cycle['fund_cycle_stage']
        snapshot = dict(snapshot)
        snapshot['emotion'] = emotion
        snapshot['breadth_read_source'] = 'MARKET_METRICS_FACT_MATCHED'
    except (sqlite3.Error, TypeError, ValueError):
        return snapshot
    finally:
        if db is not None:
            db.close()
    return snapshot


def _overlay_highest_board_fact(snapshot):
    """Read the same-day highest-board fact for the selected published batch."""
    if not isinstance(snapshot, dict):
        return snapshot
    date = str(snapshot.get('date') or '').replace('-', '')
    batch_id = str(snapshot.get('published_batch_id') or '')
    if not re.fullmatch(r'\d{8}', date) or not batch_id:
        return snapshot
    db = None
    try:
        db = sqlite3.connect(f'file:{_UPDATE_DB.as_posix()}?mode=ro', uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        gate = db.execute(
            "SELECT 1 FROM fact_read_gate WHERE family='highest_board' AND trade_date=? "
            "AND source_batch_id=? AND status='MATCH'", (date, batch_id)).fetchone()
        row = db.execute(
            "SELECT value_real,status FROM market_metrics_fact WHERE trade_date=? "
            "AND metric='highest_board' AND source_batch_id=?", (date, batch_id)).fetchone()
        if not gate or not row or row['status'] != 'VALID' or row['value_real'] is None:
            return snapshot
        highest = int(row['value_real'])
        smash = dict(snapshot.get('smash') or {})
        smash['highest_board'] = highest
        smash['highest_board_fact_source'] = 'MARKET_METRICS_FACT_MATCHED'
        snapshot = dict(snapshot)
        snapshot['smash'] = smash
        leader = dict(snapshot.get('leader') or {})
        leader['highest_board'] = highest
        snapshot['leader'] = leader
        return snapshot
    except (sqlite3.Error, TypeError, ValueError):
        return snapshot
    finally:
        if db is not None:
            db.close()

from reports.backtest_engine import build_backtest

import pandas as pd

# 更新状态（全局状态只负责当前进程；ui_update_jobs 负责跨重启审计/限次）
_update_status = {
    "running": False, "progress": "", "result": None, "error": None,
    "error_type": None, "start_time": None, "end_time": None,
    "job_id": None, "mode": None, "target_date": None, "last_heartbeat": None,
    "task_progress": None,
}
_cancel_event = threading.Event()
_UPDATE_DB = Path(__file__).resolve().parent / 'data' / '.migration_shadow' / 'market_store_5535.next.sqlite3'
_UPDATE_STEP_IDS = (
    'init', 'calendar', 'target', 'source_setup',
    'limit_up', 'previous_limit_up', 'limit_down', 'open_board',
    'previous_pool_performance', 'candidate_score_fields', 'market_breadth', 'input_validation',
    'bundle_capture', 'policy_filter', 'breadth_fact', 'smash', 'emotion',
    'money5', 'cycle', 'position', 'history', 'snapshot', 'generation_manifest',
    'publication_gate', 'hot_evidence', 'retention', 'readback',
)
_UPDATE_STEP_LABELS = {
    'init': '初始化任务与租约', 'calendar': '解析交易日历',
    'target': '确认目标日与前一交易日', 'source_setup': '初始化数据源与采集策略',
    'limit_up': '采集涨停池', 'previous_limit_up': '采集昨日涨停池',
    'limit_down': '采集跌停池', 'open_board': '采集炸板池',
    'previous_pool_performance': '采集昨日涨停表现', 'candidate_score_fields': '核验候选评分字段', 'market_breadth': '采集市场宽度',
    'input_validation': '校验采集输入与日期完整性',
    'bundle_capture': '构建原始输入与证据包', 'policy_filter': '应用范围与过滤规则',
    'breadth_fact': '保存市场宽度事实', 'smash': '计算砸盘情绪',
    'emotion': '计算市场情绪', 'money5': '同步883900五日赚钱效应', 'cycle': '计算情绪周期', 'position': '计算仓位建议',
    'history': '保存独立历史事实', 'snapshot': '生成仪表盘快照',
    'generation_manifest': '写入生成清单与哈希', 'publication_gate': '执行发布资格校验',
    'hot_evidence': '写入热库与证据库', 'retention': '执行保留与压缩策略',
    'readback': '回读校验日期与批次',
}


def _now_utc():
    return datetime.now(timezone.utc).isoformat()


def _update_db():
    if not _UPDATE_DB.exists():
        return None
    conn = sqlite3.connect(str(_UPDATE_DB), timeout=5)
    conn.execute('''CREATE TABLE IF NOT EXISTS ui_update_jobs (
        id TEXT PRIMARY KEY, target_key TEXT NOT NULL, target_date TEXT,
        mode TEXT NOT NULL, state TEXT NOT NULL, requested_at TEXT NOT NULL,
        updated_at TEXT NOT NULL, finished_at TEXT, progress_json TEXT NOT NULL,
        result_json TEXT, error TEXT, error_type TEXT)''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_ui_update_jobs_key_time ON ui_update_jobs(target_key, requested_at)')
    return conn


def _new_task(mode, target_date):
    weight = round(100 / len(_UPDATE_STEP_IDS), 2)
    return {
        'running': True, 'mode': mode, 'target_date': target_date,
        'message': '正在初始化...', 'percent': 0, 'cancel_requested': False,
        'result_status': None, 'started_at': time.time(), 'elapsed_seconds': 0,
        'current_step': 'init', 'step_count': len(_UPDATE_STEP_IDS),
        'steps': [{'id': sid, 'label': _UPDATE_STEP_LABELS[sid], 'state': 'WAITING',
                   'error': None, 'weight_percent': weight, 'percent': 0}
                  for sid in _UPDATE_STEP_IDS],
    }


def _persist_job():
    job_id = _update_status.get('job_id')
    if not job_id:
        return
    try:
        conn = _update_db()
        if conn is None:
            return
        task = _update_status.get('task_progress') or {}
        terminal = not bool(_update_status.get('running'))
        state = task.get('result_status') or ('RUNNING' if not terminal else 'DONE')
        conn.execute('''UPDATE ui_update_jobs SET state=?, target_date=?, updated_at=?,
                        finished_at=?, progress_json=?, result_json=?, error=?, error_type=? WHERE id=?''',
                     (state, _update_status.get('target_date'), _now_utc(),
                      _now_utc() if terminal else None, json.dumps(task, ensure_ascii=False),
                      json.dumps(_update_status.get('result'), ensure_ascii=False, default=str),
                      _update_status.get('error'), _update_status.get('error_type'), job_id))
        conn.commit(); conn.close()
    except Exception:
        # Progress persistence must not turn a valid collection into a failed one.
        pass


def _set_task(step_id=None, state=None, message=None, error=None):
    global _update_status
    with _update_lock:
        task = _update_status.get('task_progress') or _new_task(_update_status.get('mode'), _update_status.get('target_date'))
        if step_id and step_id in _UPDATE_STEP_IDS:
            for step in task['steps']:
                if step['id'] == step_id:
                    step['state'] = state or step['state']
                    if state == 'RUNNING':
                        task['current_step'] = step_id
                    step['percent'] = 100 if state in ('DONE', 'SKIPPED') else 0
                    if error: step['error'] = str(error)
                    break
        done = sum(1 for step in task['steps'] if step['state'] in ('DONE', 'SKIPPED'))
        failed = next((step for step in task['steps'] if step['state'] == 'FAILED'), None)
        task['percent'] = round(done * 100 / len(task['steps']), 2)
        task['elapsed_seconds'] = round(max(0, time.time() - float(task.get('started_at') or time.time())), 1)
        if message: task['message'] = message
        if failed: task['message'] = '任务失败：' + (failed.get('error') or failed['label'])
        task['cancel_requested'] = _cancel_event.is_set()
        _update_status['task_progress'] = task
        _update_status['progress'] = task['message']
        _update_status['last_heartbeat'] = time.time()
    _persist_job()


def _claim_update(mode, target_date):
    global _update_status
    with _update_lock:
        if _update_status['running']:
            return None, 'ALREADY_RUNNING'
        day_key = datetime.now().astimezone().strftime('%Y%m%d')
        target_key = f'{mode}:{target_date or "LATEST"}:{day_key}'
        job_id = uuid.uuid4().hex
        conn = _update_db()
        if conn is None:
            return None, 'JOB_STORE_UNAVAILABLE'
        rows = conn.execute('SELECT id, state FROM ui_update_jobs WHERE target_key=? ORDER BY requested_at', (target_key,)).fetchall()
        if len(rows) >= 3:
            terminal = [row for row in rows if row[1] != 'RUNNING']
            if not terminal:
                conn.close()
                return None, 'JOB_LIMIT_REACHED'
            conn.execute('DELETE FROM ui_update_jobs WHERE id=?', (terminal[0][0],))
        # 5535_JOB_GC: 新建任务时自动清理历史残留（RUNNING 永不删）
        # 规则1: 同 target_key 下，已结束任务只留最新一条（卡住重跑后旧任务自动清掉）
        conn.execute('DELETE FROM ui_update_jobs WHERE target_key=? AND state != ? AND id NOT IN (SELECT id FROM ui_update_jobs WHERE target_key=? AND state != ? ORDER BY requested_at DESC LIMIT 2)', (target_key, 'RUNNING', target_key, 'RUNNING'))
        # 规则2: 全局已结束任务只留最近 20 条，更早的删掉
        conn.execute('DELETE FROM ui_update_jobs WHERE state != ? AND id NOT IN (SELECT id FROM ui_update_jobs WHERE state != ? ORDER BY requested_at DESC LIMIT 20)', ('RUNNING', 'RUNNING'))
        now = _now_utc()
        task = _new_task(mode, target_date)
        conn.execute('''INSERT INTO ui_update_jobs
            (id,target_key,target_date,mode,state,requested_at,updated_at,progress_json)
            VALUES (?,?,?,?,?,?,?,?)''',
                     (job_id, target_key, target_date, mode, 'RUNNING', now, now,
                      json.dumps(task, ensure_ascii=False)))
        conn.commit(); conn.close()
        _cancel_event.clear()
        _update_status = {
            'running': True, 'progress': '正在初始化...', 'result': None, 'error': None,
            'error_type': None, 'start_time': time.time(), 'end_time': None,
            'job_id': job_id, 'mode': mode, 'target_date': target_date,
            'last_heartbeat': time.time(), 'task_progress': _new_task(mode, target_date),
        }
        return job_id, None


_update_lock = threading.Lock()


def run_update(_claimed=False, *, mode='UPDATE', requested_date=None):
    """The user-triggered updater calls the SAME pipeline as start.py.

    No parallel legacy computation, no yesterday_rate=0, no five-day position.
    This is not called by the read-only capture tools.
    """
    global _update_status
    if not _claimed and not _claim_update(mode, requested_date)[0]:
        return
    try:
        _set_task('init', 'RUNNING', '正在初始化任务与租约')
        _set_task('init', 'DONE', '任务租约已确认')
        _set_task('calendar', 'RUNNING', '正在解析交易日历')
        _set_task('target', 'RUNNING', '正在确认目标日与前一交易日')
        _set_task('source_setup', 'RUNNING', '正在初始化数据源与采集策略')
        from collection import trading_calendar_fallback, data_fetcher
        from collection.data_fetcher import fetch_dashboard_data
        from start import run_pipeline
        trading_calendar_fallback.install(Path(__file__).resolve().parent, data_fetcher)
        _set_task('source_setup', 'DONE', '数据源与采集策略已就绪')
        def on_collection(step_id, label, state, detail=None):
            _set_task(step_id, state, ('正在' if state == 'RUNNING' else '已完成' if state == 'DONE' else '失败：') + label,
                      (detail or {}).get('error') if detail else None)
        _set_task(message=('正在补录 ' + requested_date if mode == 'BACKFILL' else '正在获取最新交易日数据'))
        data = fetch_dashboard_data(requested_date if mode == 'BACKFILL' else None,
                                    progress_callback=on_collection, cancel_event=_cancel_event)
        _set_task('calendar', 'DONE', '交易日历已确认')
        _set_task('target', 'DONE', '目标日与前一交易日已确认')
        _set_task('input_validation', 'RUNNING', '正在校验采集输入与日期完整性')
        _set_task('input_validation', 'DONE', '采集输入与日期校验通过')
        _set_task('bundle_capture', 'RUNNING', '正在构建原始输入与证据包')
        _set_task('bundle_capture', 'DONE', '原始输入与证据包已构建')
        _set_task('money5', 'RUNNING', '正在同步883900五日赚钱效应')
        from market_speed_883900.fuyao_sync import sync_for_date
        money5_sync = sync_for_date(Path(__file__).resolve().parent, str(data.date).replace('-', ''))
        if money5_sync.get('status') == 'COMPLETE':
            _set_task('money5', 'DONE', '883900五日赚钱效应已核验入库')
        else:
            _set_task('money5', 'SKIPPED', '883900五日赚钱效应暂未就绪', money5_sync.get('error') or money5_sync.get('status'))
        _set_task('policy_filter', 'RUNNING', '正在应用范围与过滤规则')
        _set_task('policy_filter', 'DONE', '范围与过滤规则已应用')
        def on_pipeline(step_id, label, state, detail=None):
            _set_task(step_id, state,
                      ('正在' if state == 'RUNNING' else '已完成' if state == 'DONE' else '失败：') + label,
                      (detail or {}).get('error') if detail else None)
        result, manifest = run_pipeline(data, persist_history=True, build_text_report=False,
                                        archive_only=False, progress_callback=on_pipeline)
        # The publication gate can reject a DATA_PENDING result. Prepare its
        # diagnostics before entering that gate so the rejection itself never
        # masks the real reason with an unbound local variable error.
        emotion = result.get('emotion') or {}
        smash = result.get('smash') or {}
        position = result.get('position') or {}
        _set_task('generation_manifest', 'DONE', '生成清单与哈希已写入')
        _set_task('publication_gate', 'RUNNING', '正在执行发布资格校验')
        from publish_completed_generation import publish
        try:
            publication = publish(Path(__file__).resolve().parent, result)
            _set_task('publication_gate', 'DONE', '发布资格校验通过')
            _set_task('hot_evidence', 'DONE', '热库与证据库已写入')
            _set_task('retention', 'DONE', '保留与压缩策略已执行')
        except ValueError as exc:
            message = str(exc)
            if not message.startswith('PENDING_GENERATION_NOT_PUBLISHED'):
                raise
            missing = list(emotion.get('missing_fields') or [])
            gate_reason = message.partition(': ')[2]
            reason = gate_reason or ('；'.join(missing) if missing else '发布资格校验未通过：请查看待核预览中的数据来源与日期校验状态')
            # DATA_PENDING is an expected terminal state: the generation is
            # retained for diagnosis, but incomplete evidence is never
            # promoted into the published hot/evidence stores.
            publication = {
                'status': 'PENDING_GENERATION_NOT_PUBLISHED',
                'published': False,
                'reason': '生成结果仍有待核证据，未写入已发布热库：' + reason,
            }
            _set_task('publication_gate', 'BLOCKED',
                      '发布阻断：PENDING_GENERATION_NOT_PUBLISHED', str(exc))
            _set_task('hot_evidence', 'SKIPPED', '未发布，跳过热库与证据库写入')
            _set_task('retention', 'SKIPPED', '未发布，跳过发布后保留压缩')
        result['fact_publication'] = publication
        _set_task('readback', 'RUNNING', '正在回读校验生成日期与发布批次')
        storage = publication.get('storage') or {}
        pending = emotion.get('status') != 'VALID'
        _update_status['result'] = {
            'date': result.get('date'), 'emotion_score': emotion.get('score'),
            'smash_score': smash.get('score'), 'highest_board': smash.get('highest_board'),
            'highest_stock': smash.get('leader'), 'limit_up_count': (result.get('limit') or {}).get('up'),
            'limit_down_count': (result.get('limit') or {}).get('down'),
            'cycle_stage': emotion.get('cycle_stage'),
            'position_suggest': position.get('suggest') or position.get('position'),
            'status': 'DATA_PENDING' if pending else 'GENERATED_NOT_STRATEGY_ACCEPTANCE',
            'schema_version': result.get('schema_version'), 'cycle_status': (result.get('cycle') or {}).get('status'),
            'position_status': (result.get('position') or {}).get('status'),
            'publication_status': publication.get('status'),
            'publication_reason': publication.get('reason'),
            'runtime_warnings': manifest.get('runtime_warnings', []),
            'source_imports': manifest.get('source_imports', {}),
            'storage_budget_status': storage.get('budget_status'),
            'storage_daily_evidence_bytes': storage.get('daily_evidence_bytes'),
            'storage_evidence_bytes_added': storage.get('evidence_bytes_added'),
            'duration': round(time.time() - _update_status['start_time'], 1),
        }
        _set_task('readback', 'DONE', '生成日期与发布状态回读完成')
        if storage.get('budget_status') == 'OVER_BUDGET':
            _update_status['progress'] = '采集已完成，但当日新增存储超过 3 MiB 预算'
        else:
            _update_status['progress'] = '已生成待证据快照，不能视为行情核验通过' if pending else '统一流程已生成；正式策略仍未启用'
        _update_status['task_progress']['result_status'] = (
            'DATA_PENDING' if publication.get('status') == 'PENDING_GENERATION_NOT_PUBLISHED' else 'DONE'
        )
        if publication.get('status') == 'PENDING_GENERATION_NOT_PUBLISHED':
            _update_status['progress'] = '生成完成，但证据待核，未发布到热库'
    except Exception as exc:
        cancelled = _cancel_event.is_set() or type(exc).__name__ in ('DataCollectionCancelled',)
        _update_status['error'] = str(exc)
        _update_status['error_type'] = type(exc).__name__
        _update_status['progress'] = '任务已停止' if cancelled else '任务失败，已停止后续分支'
        task = _update_status.get('task_progress') or _new_task(mode, requested_date)
        for step in task.get('steps', []):
            if step.get('state') == 'RUNNING':
                step['state'] = 'FAILED' if not cancelled else 'BLOCKED'
                step['error'] = str(exc)
            elif step.get('state') == 'WAITING':
                step['state'] = 'BLOCKED'
                step['error'] = '前置阶段失败，未执行该分支'
        task['result_status'] = 'CANCELLED' if cancelled else 'FAILED'
        task['running'] = False
        task['message'] = _update_status['progress']
        _update_status['task_progress'] = task
    finally:
        with _update_lock:
            _update_status['end_time'] = time.time()
            _update_status['running'] = False
            if _update_status.get('task_progress'):
                _update_status['task_progress']['running'] = False
                started = float(_update_status['task_progress'].get('started_at') or _update_status['start_time'] or time.time())
                _update_status['task_progress']['elapsed_seconds'] = round(max(0, _update_status['end_time'] - started), 1)
        _persist_job()


app = Flask(__name__)

VERSION = "3.5.6"

SNAPSHOT_DIR = (
    Path(__file__).parent
    /
    "data"
    /
    "dashboards"
)


def _published_snapshot(requested_date=None):
    """Read the exact published batch; never infer a current date from a file."""
    db = None
    try:
        db = sqlite3.connect(f'file:{_UPDATE_DB.as_posix()}?mode=ro', uri=True)
        db.row_factory = sqlite3.Row
        where = 'WHERE p.trade_date=?' if requested_date else ''
        row = db.execute(
            'SELECT p.trade_date, b.id AS batch_id, b.snapshot_json '
            'FROM published_days p JOIN batches b ON b.id=p.batch_id '
            + where + ' ORDER BY p.trade_date DESC LIMIT 1',
            (requested_date,) if requested_date else (),
        ).fetchone()
        if not row:
            return None
        raw = row['snapshot_json']
        if isinstance(raw, bytes):
            raw = raw.decode('utf-8-sig')
        snapshot = json.loads(raw, parse_constant=lambda _: None)
        if not isinstance(snapshot, dict) or str(snapshot.get('date') or '') != row['trade_date']:
            return None
        snapshot['published_batch_id'] = row['batch_id']
        snapshot['snapshot_read'] = {'status': 'PUBLISHED_BATCH'}
        return snapshot
    except (sqlite3.Error, ValueError, UnicodeError, TypeError):
        return None
    finally:
        if db is not None:
            db.close()


def _available_dashboard_dates():
    db = None
    dates = set()
    try:
        db = sqlite3.connect(f'file:{_UPDATE_DB.as_posix()}?mode=ro', uri=True)
        rows = db.execute(
            'SELECT p.trade_date FROM published_days p '
            'JOIN batches b ON b.id=p.batch_id '
            'WHERE b.quality_status=?',
            ('VALID_MARKET_INPUT',),
        )
        for row in rows:
            d = str(row[0])
            if re.fullmatch(r'\d{8}', d):
                dates.add(d)
        return sorted(dates, reverse=True)
    except sqlite3.Error:
        return sorted(dates, reverse=True)
    finally:
        if db is not None:
            db.close()


def _unpublished_generation_snapshot():
    """Return the latest generated snapshot strictly as an unpublished preview."""
    path = Path(__file__).resolve().parent / 'data' / 'last_generation' / 'dashboard.json'
    try:
        snapshot = json.loads(path.read_text(encoding='utf-8'))
        date = str(snapshot.get('date') or '')
        if not re.fullmatch(r'\d{8}', date):
            return None
        snapshot['draft_preview'] = True
        snapshot['snapshot_read'] = {'status': 'UNPUBLISHED_GENERATION_PREVIEW'}
        snapshot['preview_notice'] = '此为待核生成结果，仅供核对；未写入已发布热库，也不会进入已发布回放。'
        return snapshot
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _snapshot_history(target_date: str) -> list:
    """
    截至指定交易日的情绪历史（最多5条，供回放页五日周期图使用）
    """

    try:

        history = load_history()

        if not hasattr(history, "to_dict"):
            return []

        records = history.to_dict("records")

        if target_date:

            records = [
                r for r in records
                if str(r.get("date", "")) <= str(target_date)
            ]

        return _clean(records[-5:])

    except Exception:

        return []


def _snapshot_smash_history(target_date: str) -> list:
    """
    截至指定交易日的砸盘历史（供回放页砸盘折线图使用）
    返回全部历史，前端 dataZoom 控制显示范围，可拖动查看更早数据
    """

    try:

        all_rows = load_smash_history(200)

        if target_date:

            all_rows = [
                r for r in all_rows
                if str(r.get("date", "")) <= str(target_date)
            ]

        return _clean(all_rows)

    except Exception:

        return []


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/backtest')
def backtest():
    return render_template('backtest.html')


@app.route('/api/backtest')
def api_backtest():
    """
    V3.2 历史回测数据
    概览统计 + 情绪分区间回测 + 砸盘回测 + 最高板回测 + 历史走势
    """
    return jsonify(build_backtest())


@app.route('/api/dashboard')
def api_dashboard():
    """Pass through the actual snapshot including new evidence/status fields."""
    date = str(request.args.get('date', '') or '').strip()
    preview = str(request.args.get('preview', '') or '').strip() == '1'
    if date and not re.fullmatch(r'\d{8}', date):
        return jsonify({'error': '日期必须为YYYYMMDD', 'error_type': 'INVALID_DATE'}), 400
    published = _unpublished_generation_snapshot() if preview else _published_snapshot(date or None)
    if not published:
        payload = {
            'error': '暂无未发布预览' if preview else '暂无已发布数据，请点击“更新数据”完成首次采集',
            'error_type': 'NO_UNPUBLISHED_PREVIEW' if preview else 'NO_PUBLISHED_SNAPSHOT',
        }
        if not preview:
            pending = _unpublished_generation_snapshot()
            if pending:
                payload['unpublished_preview_available'] = True
                payload['unpublished_preview_date'] = pending.get('date')
        return jsonify(payload), 404
    if date and str(published.get('date') or '') != date:
        return jsonify({'error': '预览日期不匹配', 'error_type': 'PREVIEW_DATE_MISMATCH'}), 404
    if not preview:
        published = _overlay_highest_board_fact(_overlay_market_breadth_score(
            _attach_market_breadth_fact(_attach_money_cycle_position(published))
        ))
        if not date:
            try:
                from collection import data_fetcher
                published['market_session'] = data_fetcher.market_session()
            except RuntimeError:
                pass
    published['history'] = _snapshot_history(str(published.get('date') or ''))
    published['smash_history'] = _snapshot_smash_history(str(published.get('date') or ''))
    return jsonify(_clean(published))


@app.route('/api/cockpit')
def api_cockpit():
    """Compatibility read for the current dashboard client.

    The cockpit client predates the dashboard route, but both surfaces use the
    same validated snapshot. Keeping this as a thin adapter prevents an HTML
    page from loading successfully while its first data request returns 404.
    """
    response = api_dashboard()
    status = 200
    if isinstance(response, tuple):
        response, status = response
    payload = response.get_json(silent=True) if hasattr(response, 'get_json') else None
    if not isinstance(payload, dict):
        return response

    preview = bool(payload.get('draft_preview'))
    dates = []
    try:
        dates.extend(_available_dashboard_dates())
    except:
        pass
    current_date = str(payload.get('date') or '')
    if not preview and re.fullmatch(r'\d{8}', current_date):
        dates.append(current_date)
    payload['navigation_dates'] = sorted(set(dates), reverse=True)
    payload['cockpit_transport'] = 'UNPUBLISHED_PREVIEW' if preview else 'DASHBOARD_COMPAT_V1'
    return jsonify(_clean(payload)), status


@app.route('/api/research/money-effect')
def api_research_money_effect_v2():
    """Read the matched five-session money-effect fact for the requested day."""
    date = str(request.args.get('date', '') or '').strip()
    if date and not re.fullmatch(r'\d{8}', date):
        return jsonify({'error': '日期必须为YYYYMMDD', 'error_type': 'INVALID_DATE'}), 400
    if not date:
        date = str(build_dashboard().get('date') or '')
    db_path = Path(__file__).resolve().parent / 'data' / '.migration_shadow' / 'market_store_5535.next.sqlite3'
    if not db_path.is_file():
        return jsonify({'error': '计算结果事实库不存在', 'error_type': 'FACT_DB_MISSING'}), 404
    try:
        db = sqlite3.connect(f'file:{db_path.as_posix()}?mode=ro', uri=True)
        db.row_factory = sqlite3.Row
        batch = db.execute(
            'SELECT b.id, b.trade_date FROM published_days p '
            'JOIN batches_fact b ON b.id=p.batch_id WHERE p.trade_date=?',
            (date,),
        ).fetchone()
        if not batch:
            return jsonify({'error': '该交易日没有事实批次', 'error_type': 'FACT_BATCH_MISSING'}), 404
        gate = db.execute(
            "SELECT status FROM fact_read_gate WHERE family='money5' AND trade_date=? AND source_batch_id=?",
            (batch['trade_date'], batch['id']),
        ).fetchone()
        if not gate or gate['status'] != 'MATCH':
            from market_speed_883900 import storage
            from market_speed_883900.money_view import make_view
            from collection.trading_calendar_cache import read_cached_days
            if storage.active(db_path):
                records = storage.daily_rows(db_path)
                first_record = min(records, default=batch['trade_date'])
                view = make_view(read_cached_days(), records, batch['trade_date'], start=first_record)
                if (view.get('current') or {}).get('status') == 'VALID':
                    view.update({'schema': 'MONEY_EFFECT_INDEX_V1', 'trade_date': batch['trade_date'],
                                 'read_source': 'M8839_PERSISTED_INDEX'})
                    return jsonify(view)
            return jsonify({'error': '该日五日赚钱效应尚未通过同日同批次校验', 'error_type': 'FACT_NOT_MATCHED'}), 404
        row = db.execute(
            'SELECT trade_date,source_batch_id,earning_effect,fund_cycle,fund_cycle_exact,stage,status,rule_version '
            'FROM money_effect_daily WHERE trade_date=? AND source_batch_id=?',
            (batch['trade_date'], batch['id']),
        ).fetchone()
        if not row:
            return jsonify({'error': '该日五日赚钱效应事实不存在', 'error_type': 'FACT_RESULT_MISSING'}), 404
        result = dict(row)
        result['window'] = [dict(item) for item in db.execute(
            'SELECT sequence_no,window_date,earning_effect,source_batch_ref,status '
            'FROM money_effect_window WHERE trade_date=? AND source_batch_id=? ORDER BY sequence_no',
            (batch['trade_date'], batch['id']),
        )]
        history = [dict(item) for item in db.execute(
            'SELECT trade_date,source_batch_id,earning_effect,fund_cycle,fund_cycle_exact,stage,status,rule_version '
            'FROM v_money_effect_published WHERE trade_date<=? ORDER BY trade_date',
            (batch['trade_date'],),
        )]
        return jsonify({'schema': 'MONEY_EFFECT_FACTS_V2', 'trade_date': batch['trade_date'],
                        'source_batch_id': batch['id'], 'result': result,
                        'history': history,
                        'read_source': 'V2_FACT_MATCHED'})
    except sqlite3.Error as exc:
        return jsonify({'error': '五日赚钱效应事实读取失败', 'error_type': type(exc).__name__}), 500
    finally:
        try:
            db.close()
        except Exception:
            pass


@app.route('/api/health')
def api_health():
    """Read-only service/process evidence; does not fetch quotes or start jobs."""
    import os
    import sys
    import dashboard_data
    imports = {}
    for name in ('web_app', 'dashboard_data', 'start', 'dashboard_snapshot', 'market_pipeline'):
        mod = sys.modules.get(name)
        if name == 'web_app' and mod is None and __name__ == '__main__':
            mod = sys.modules.get('__main__')
        path = getattr(mod, '__file__', None)
        if path and Path(path).is_file():
            imports[name] = {'path': str(Path(path).resolve()),
                             'disk_sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest()}
    return jsonify({'status': 'SERVING', 'pid': os.getpid(), 'python': sys.executable,
                    'version': VERSION, 'snapshot_path': str(dashboard_data.DASHBOARD_FILE),
                    'snapshot_exists': dashboard_data.DASHBOARD_FILE.is_file(),
                    'loaded_module_paths': imports,
                    'note': '磁盘哈希不是运行中函数字节码证明；服务可达不等于行情有效'})


@app.route('/api/dates')
def api_dates():
    """
    可用回放交易日（倒序，最新在前）
    """

    return jsonify({"dates": _available_dashboard_dates()})


@app.route('/api/market/session')
def api_market_session():
    """Expose the server-authoritative trade-calendar and close-time decision."""
    try:
        from collection import data_fetcher, trading_calendar_fallback
        trading_calendar_fallback.install(Path(__file__).resolve().parent, data_fetcher)
        return jsonify(data_fetcher.market_session())
    except RuntimeError as exc:
        return jsonify({'error': str(exc), 'error_type': 'TRADE_CALENDAR_UNAVAILABLE'}), 503


def _backfill_trade_dates(month: str) -> list[str]:
    if not re.fullmatch(r'\d{6}', month):
        raise ValueError('月份必须为YYYYMM')
    year, month_number = int(month[:4]), int(month[4:])
    if not 1 <= month_number <= 12:
        raise ValueError('月份必须为YYYYMM')
    now = datetime.now(timezone(timedelta(hours=8)))
    from collection import data_fetcher, trading_calendar_fallback
    trading_calendar_fallback.install(Path(__file__).resolve().parent, data_fetcher)
    last_day = calendar.monthrange(year, month_number)[1]
    end_date = f'{month}{last_day:02d}'
    today = now.strftime('%Y%m%d')
    if end_date > today:
        end_date = today
    if month == now.strftime('%Y%m'):
        end_date = min(end_date, data_fetcher.market_session(now)['latest_completed_trade_date'])
    if end_date < f'{month}01':
        return []
    return [date for date in data_fetcher.get_trade_dates(end_date, count=40)
            if date.startswith(month)]


@app.route('/api/trading-calendar')
def api_trading_calendar():
    """返回本地缓存的A股交易日历。

    优先读 data/trading_calendar_cache.json（毫秒级，不打外部 API）。
    仅当缓存文件缺失时才同步请求一次同花顺 API 并写盘；失败返回空数组，
    前端用内置 fallback 兜底，不阻塞日历浮窗渲染。
    """
    from collection.trading_calendar_cache import read_cached_days, refresh_trading_days
    days = read_cached_days()
    source = 'local_cache'
    if not days:
        try:
            days = refresh_trading_days()
            source = 'provider_fetched'
        except Exception:
            days = []
            source = 'unavailable'
    return jsonify({'days': days, 'source': source})


@app.route('/api/backfill/dates')
def api_backfill_dates():
    month = str(request.args.get('month') or datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m')).strip()
    try:
        dates = _backfill_trade_dates(month)
    except (RuntimeError, ValueError) as exc:
        return jsonify({'error': str(exc), 'error_type': 'TRADE_CALENDAR_UNAVAILABLE'}), 503
    return jsonify({'month': month, 'dates': dates,
                    'source': 'VERIFIED_TRADE_CALENDAR',
                    'note': '日期仅用于选择补录；成功发布后才会进入回放日期列表'})


@app.route('/api/history')
def api_history():
    """
    完整情绪历史（含最高板、涨停数等）

    供 V3.2 历史回测页面使用
    """

    try:

        history = load_history()

        records = (
            history.to_dict("records")
            if hasattr(history, "to_dict")
            else []
        )

    except Exception:

        records = []

    return jsonify({
        "history": _clean(records)
    })


@app.route('/api/update', methods=['POST'])
def api_update():
    """Start latest-day update or an explicitly selected historical backfill."""
    payload = request.get_json(silent=True) or {}
    requested_date = str(payload.get('requested_date') or '').strip()
    if requested_date and not re.fullmatch(r'\d{8}', requested_date):
        return jsonify({'status': 'error', 'error_type': 'INVALID_DATE', 'error': '日期必须为YYYYMMDD'}), 400
    if not requested_date:
        try:
            from collection import data_fetcher
            session = data_fetcher.market_session()
        except RuntimeError as exc:
            return jsonify({'status': 'error', 'error_type': 'TRADE_CALENDAR_UNAVAILABLE',
                            'error': str(exc)}), 503
        if not session['update_enabled']:
            return jsonify({'status': 'error', 'error_type': 'MARKET_NOT_CLOSED',
                            'error': session['reason'],
                            'latest_completed_trade_date': session['latest_completed_trade_date']}), 409
    mode = 'BACKFILL' if requested_date else 'UPDATE'
    try:
        job_id, reason = _claim_update(mode, requested_date or None)
    except sqlite3.OperationalError as exc:
        # A locked/read-only task store must not surface as an opaque 500.
        # No collector has started at this point, so the caller can retry
        # after restoring write access to the hot database directory.
        return jsonify({'status': 'error', 'error_type': 'JOB_STORE_WRITE_FAILED',
                        'error': '任务记录库无法写入，请检查热库文件和目录权限：' + str(exc)}), 503
    if reason == 'ALREADY_RUNNING':
        return jsonify({'status': 'already_running', 'message': '已有采集/计算任务正在进行中',
                        'progress': _update_status['progress'], 'task_progress': _update_status['task_progress']}), 202
    if reason == 'JOB_LIMIT_REACHED':
        return jsonify({'status': 'error', 'error_type': 'JOB_LIMIT_REACHED',
                        'error': '同一操作日同一目标最多保留3次任务，请等待当前任务结束或次日重试'}), 429
    if reason == 'JOB_STORE_UNAVAILABLE':
        return jsonify({'status': 'error', 'error_type': 'JOB_STORE_UNAVAILABLE',
                        'error': '任务记录库不可用，为避免重复采集已拒绝启动'}), 503
    try:
        thread = threading.Thread(target=run_update, kwargs={
            '_claimed': True, 'mode': mode, 'requested_date': requested_date or None,
        }, daemon=True, name=f'5535-{mode.lower()}-{job_id[:8]}')
        thread.start()
        _spawn_log_cleanup()
        _maybe_prefetch_next_month_calendar(mode)
    except Exception as exc:
        with _update_lock:
            _update_status.update(running=False, error=str(exc), end_time=time.time())
            _update_status['task_progress']['result_status'] = 'FAILED'
        _persist_job()
        return jsonify({'status': 'error', 'error': str(exc)}), 500
    return jsonify({'status': 'started', 'job_id': job_id, 'mode': mode,
                    'target_date': requested_date or None,
                    'message': '历史补录任务已启动' if mode == 'BACKFILL' else '最新交易日更新任务已启动',
                    'progress': _update_status['progress'],
                    'task_progress': _update_status['task_progress']}), 202


def _spawn_log_cleanup():
    """后台异步清理热库日志与压缩旧修订（独立进程，不阻塞采集/Web）。失败仅记录，不影响主流程。"""
    import sys as _sys, pathlib as _pathlib
    try:
        script = _pathlib.Path(__file__).resolve().parent / 'tools' / 'cleanup_auto.py'
        if not script.exists():
            return
        python = _sys.executable
        kwargs = {}
        if _sys.platform == 'win32':
            kwargs['creationflags'] = 0x08000000  # CREATE_NO_WINDOW
        subprocess.Popen(
            [python, '-S', str(script)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd=str(script.parent.parent),
            **kwargs
        )
    except Exception:
        pass
    # 5535_PAYLOAD_COMPACT_R1: 同日去重 + 非head修订/runs 压缩（幂等，只写不读表安全）
    try:
        script2 = _pathlib.Path(__file__).resolve().parent / 'tools' / 'compact_payloads.py'
        if not script2.exists():
            return
        python = _sys.executable
        kwargs = {}
        if _sys.platform == 'win32':
            kwargs['creationflags'] = 0x08000000  # CREATE_NO_WINDOW
        subprocess.Popen(
            [python, '-S', str(script2)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd=str(script2.parent.parent),
            **kwargs
        )
    except Exception:
        pass


def _maybe_prefetch_next_month_calendar(mode: str):
    """本月最后三个交易日点“更新数据”时，后台异步拉取下月交易日历并写本地缓存。

    BACKFILL 历史补录不触发；失败只记日志，不影响主更新任务。
    """
    if mode != 'UPDATE':
        return
    try:
        from datetime import datetime as _dt
        from collection.trading_calendar_cache import (
            get_trading_days_cached, refresh_trading_days, is_tail_trading_day,
        )
        today = _dt.now().strftime('%Y%m%d')
        days = get_trading_days_cached()
        if not is_tail_trading_day(today, days, 3):
            return
        def _job():
            try:
                refresh_trading_days()
            except Exception:
                pass
        threading.Thread(target=_job, daemon=True, name='5535-calendar-prefetch').start()
    except Exception:
        pass


_cleanup_scheduler_started = False


def _start_cleanup_scheduler():
    """Run abnormal-job cleanup once at startup and then every 24 hours."""
    global _cleanup_scheduler_started
    if _cleanup_scheduler_started:
        return
    _cleanup_scheduler_started = True
    _spawn_log_cleanup()

    def loop():
        while True:
            time.sleep(24 * 60 * 60)
            _spawn_log_cleanup()

    threading.Thread(target=loop, name='5535-daily-cleanup', daemon=True).start()


@app.route('/api/update/status')
def api_update_status():
    """查询更新进度"""
    global _update_status
    # Some provider calls cover a whole cohort and do not emit a callback for
    # each member. Keep the UI timer truthful during that quiet interval, then
    # freeze it at end_time once the task reaches a terminal state.
    task = _update_status.get('task_progress')
    if task and _update_status.get('start_time') is not None:
        started = float(task.get('started_at') or _update_status['start_time'])
        ended = _update_status.get('end_time') or time.time()
        task['elapsed_seconds'] = round(max(0, float(ended) - started), 1)
    if _update_status.get('running') and _update_status.get('last_heartbeat'):
        age = time.time() - _update_status['last_heartbeat']
        if age > 900:
            _cancel_event.set()
            _update_status['progress'] = '任务长时间无进展，已请求停止'
            if _update_status.get('task_progress'):
                _update_status['task_progress']['cancel_requested'] = True
                _update_status['task_progress']['message'] = _update_status['progress']
            _persist_job()
    return jsonify({
        "running": _update_status["running"],
        "progress": _update_status["progress"],
        "result": _update_status["result"],
        "error": _update_status["error"],
        "start_time": _update_status["start_time"],
        "end_time": _update_status["end_time"],
        "job_id": _update_status.get('job_id'),
        "mode": _update_status.get('mode'),
        "target_date": _update_status.get('target_date'),
        "task_progress": _update_status.get('task_progress'),
    })


@app.route('/api/update/cancel', methods=['POST'])
def api_update_cancel():
    """Cooperatively stop the active collection/calculation job."""
    if not _update_status.get('running'):
        return jsonify({'status': 'idle', 'task_progress': _update_status.get('task_progress')}), 409
    _cancel_event.set()
    with _update_lock:
        task = _update_status.get('task_progress') or {}
        task['cancel_requested'] = True
        task['message'] = '正在请求停止当前任务...'
        _update_status['task_progress'] = task
        _update_status['progress'] = task['message']
    _persist_job()
    return jsonify({'status': 'cancellation_requested', 'task_progress': _update_status['task_progress']}), 202



# ============================================================
# 数据与验证只读页面 (Phase2-Web01)
# ============================================================

BASE_DIR = Path(__file__).parent
PHASE2_DIR = BASE_DIR / "phase2_shadow"
FIXTURES_DIR = PHASE2_DIR / "fixtures" / "source"


def _load_json_safe(path):
    """安全加载JSON，失败返回None"""
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


def _load_validation_data(requested_date=None):
    """
    R2修复：使用共享snapshot_loader模块加载和校验快照。
    C1: 统一路径配置，复用读取/校验函数
    C2: content_hash校验、日期校验、结构校验、重复股检测
    只读，不修改任何源数据。
    """
    config = get_config()
    data, load_status, errors = load_validation_data(config, requested_date)

    if data is None:
        # 加载失败：返回错误结构
        error_map = {
            "FILE_MISSING": ("SNAPSHOT_FILE_MISSING", "快照文件不存在"),
            "JSON_CORRUPTED": ("SNAPSHOT_CORRUPTED", "快照JSON损坏"),
            "STRUCTURE_INVALID": ("SNAPSHOT_STRUCTURE_INVALID", "快照结构无效"),
            "READ_ERROR": ("SNAPSHOT_READ_ERROR", "快照读取失败"),
            "HASH_MISSING": ("SNAPSHOT_HASH_MISSING", "快照缺少content_hash"),
            "HASH_MISMATCH": ("SNAPSHOT_HASH_MISMATCH", "内容哈希不匹配（可能被篡改）"),
            "DATE_NOT_FOUND": ("SNAPSHOT_DATE_NOT_FOUND", "请求日期不在可用日期列表中"),
            "READ_ERROR": ("SNAPSHOT_READ_ERROR", "快照读取错误"),
        }
        err_type, err_msg = error_map.get(load_status, ("SNAPSHOT_UNKNOWN_ERROR", "未知错误"))
        return {
            "snapshot_id": "load_error",
            "trade_date": None,
            "page_title": "数据与验证",
            "page_subtitle": err_msg,
            "error_type": err_type,
            "error_message": "; ".join(errors),
            "snapshot_path": str(config.snapshot_path),
            "market_overview": {"status": "MISSING", "error": err_msg},
            "market_metrics": [],
            "candidates": [],
            "legacy_results": [],
            "legacy_replay_verification": {"status": "UNKNOWN", "reason": err_msg},
            "shadow_results": [],
            "data_quality": None,
            "feature_progress": [],
            "remaining_issues": errors,
            "new_policy_implemented": False,
        }

    # C2: 合法空候选（candidates=[]但结构有效）不是错误
    candidates = data.get("candidates", [])
    if not candidates and not data.get("empty_candidates"):
        data["empty_candidates"] = True
        data["empty_note"] = "该日无候选（快照合法，候选列表为空），市场指标仍正常展示"

    # 附加页面标题
    data.setdefault("page_title", "数据与验证")
    if load_status != "OK":
        data["error_type"] = "SNAPSHOT_" + load_status
        data["error_message"] = "; ".join(errors)

    return data


@app.route('/validation')
def validation_page():
    """数据与验证只读页面"""
    return render_template('validation.html')


@app.route('/api/validation')
def api_validation():
    """数据与验证页面JSON API（Web02.1: 统一错误出口）"""
    requested_date = request.args.get('date')
    data = _load_validation_data(requested_date)
    # Web02.1: 根据load_status返回正确HTTP状态码
    load_status = data.get("_load_status", data.get("error_type", "OK"))
    if load_status in ("DATE_NOT_FOUND", "FILE_MISSING", "SNAPSHOT_DATE_NOT_FOUND", "SNAPSHOT_FILE_MISSING"):
        return jsonify(data), 404
    elif load_status in ("JSON_CORRUPTED", "STRUCTURE_INVALID", "HASH_MISSING", "HASH_MISMATCH",
                          "SNAPSHOT_CORRUPTED", "SNAPSHOT_STRUCTURE_INVALID", "SNAPSHOT_HASH_MISSING",
                          "SNAPSHOT_HASH_MISMATCH"):
        return jsonify(data), 400
    elif load_status in ("READ_ERROR", "SNAPSHOT_READ_ERROR"):
        return jsonify(data), 500
    return jsonify(data), 200


# ========== Phase2-03A: 周期与主线研究页 ==========
@app.route('/research/cycle-theme')
def research_cycle_theme_page():
    """周期与主线研究页（只读）"""
    return render_template('research_cycle_theme.html')


@app.route('/api/research/cycle-theme')
def api_research_cycle_theme():
    """周期与主线研究页API（只读）"""
    requested_date = request.args.get('date')
    try:
        view, load_status, errors = load_cycle_theme_data(requested_date=requested_date)
    except Exception as e:
        return jsonify({
            "error": True,
            "error_type": "INTERNAL_ERROR",
            "error_message": str(e),
            "provenance": {"load_status": "ERROR", "load_errors": [str(e)]}
        }), 500

    if view.get("error"):
        if load_status in ("DATE_NOT_FOUND", "FILE_MISSING", "SNAPSHOT_DATE_NOT_FOUND", "SNAPSHOT_FILE_MISSING"):
            return jsonify(view), 404
        elif load_status in ("JSON_CORRUPTED", "STRUCTURE_INVALID", "HASH_MISSING", "HASH_MISMATCH",
                             "SNAPSHOT_CORRUPTED", "SNAPSHOT_STRUCTURE_INVALID", "SNAPSHOT_HASH_MISSING",
                             "SNAPSHOT_HASH_MISMATCH"):
            return jsonify(view), 400
        elif load_status in ("READ_ERROR", "SNAPSHOT_READ_ERROR"):
            return jsonify(view), 500
        return jsonify(view), 400
    return jsonify(view), 200


@app.route('/api/research/evidence-ledger')
def api_research_evidence_ledger():
    """03B-01 资料与证据台账API（只读）"""
    requested_date = request.args.get('date', '20260904')

    # 日期校验：本轮只支持20260904
    if requested_date != '20260904':
        return jsonify({
            "error": True,
            "error_type": "DATE_NOT_SUPPORTED",
            "error_message": f"当前台账仅支持trade_date=20260904，请求日期={requested_date}",
            "supported_dates": ["20260904"],
        }), 404

    try:
        project_root = str(Path(__file__).parent.resolve())
        records_path = str(Path(project_root) / 'research_evidence' / 'records.json')

        view = build_ledger_view(
            project_root=project_root,
            records_path=records_path,
        )
        return jsonify(view), 200
    except LedgerRootError as e:
        # 根级输入错误：文件缺失/坏JSON/根日期/scope/cutoff不符
        # 统一返回400（根输入错误），不返回200
        return jsonify({
            "error": True,
            "error_type": e.error_type,
            "error_message": e.error_message,
        }), 400
    except Exception as e:
        return jsonify({
            "error": True,
            "error_type": "INTERNAL_ERROR",
            "error_message": str(e),
        }), 500


# P49: archive is an independent, paused, read-only module.
@app.route('/research/theme-review')
def research_theme_review_archive():
    return render_template('research_theme_review_archive.html')


# BEGIN P48 READONLY THEME-REVIEW REVISION DISPLAY
@app.route('/api/research/theme-review')
def api_research_theme_review():
    """只读加载已保存的题材复核修订（theme_factor_review_revisions），构造独立展示面板。

    只读 SELECT；不写库、不触发迁移、不联网、不补数、不重算、不改原研究。
    目标修订固定 88d84cac...（20260914 / 42e50d3c）。其他日期/批次未命中时返回
    404 NO_REVISION_FOR_SCOPE，绝不拿 20260914 结果作为其他范围兜底。
    """
    from review_revision_view import (resolve_database_path, build_panel_for_target,
                                      scope_is_target, latest_published_date,
                                      TARGET_BASE_BATCH, TARGET_TRADE_DATE)
    from review_revision_sqlite import ReviewNotFound, RepositoryError, UnsupportedLayout
    from review_revision_panel import ReviewValidationError

    date = str(request.args.get('date', '') or '').strip()
    if date and not re.fullmatch(r'\d{8}', date):
        return jsonify({'error': '日期必须为YYYYMMDD', 'error_type': 'INVALID_DATE'}), 400
    if date:
        scope_date = date
    else:
        # 空 date：跟随主站实际展示的最新已发布交易日（Store/published_days），
        # 而不是可能滞后的 build_dashboard() 本地文件日期。
        try:
            scope_date = latest_published_date(resolve_database_path(__file__))
        except Exception:
            scope_date = str(build_dashboard().get('date') or '')
    if not scope_is_target(TARGET_BASE_BATCH, scope_date):
        return jsonify({'state': 'NO_REVISION_FOR_SCOPE', 'date': scope_date,
                        'message': '该展示范围没有对应的题材复核修订；不展示其他日期的结果作为兜底',
                        'schema': None, 'panel': None}), 404
    try:
        db = resolve_database_path(__file__)
        model, trace, scope = build_panel_for_target(db)
        return jsonify({'state': 'READY', 'schema': 'P48_THEME_REVIEW_PANEL_V1',
                        'date': scope_date, 'scope': scope, 'panel': model,
                        'read_trace': trace})
    except ReviewNotFound as exc:
        return jsonify({'state': 'NOT_FOUND', 'error': str(exc)}), 404
    except (RepositoryError, UnsupportedLayout) as exc:
        return jsonify({'state': 'ERROR', 'error_type': type(exc).__name__, 'error': str(exc)}), 500
    except ReviewValidationError as exc:
        return jsonify({'state': 'ERROR', 'error_type': 'REVIEW_VALIDATION', 'error': str(exc)}), 500
    except Exception as exc:
        return jsonify({'state': 'ERROR', 'error_type': 'INTERNAL_ERROR',
                        'error_message': str(exc)}), 500
# END P48 READONLY THEME-REVIEW REVISION DISPLAY


# BEGIN 5535 AUTOMATION DATABASE HOOK
from automation.automation_5535_bridge import attach_5535_database
attach_5535_database(app, __file__)
# END 5535 AUTOMATION DATABASE HOOK

# BEGIN P50 DATABASE-ONLY GATEWAY (serving layer)
# /api/* reads come from the P50 serving layer published from the original
# engine recomputation; unmapped dates fail explicitly (DB_ROUTE_NOT_MATERIALIZED)
# instead of reading old files. The update button keeps using the 5535
# automation pipeline; P50 re-publication is a separate explicit step.
try:
    import threading as _threading
    import time as _time
    from pathlib import Path as _Path
    from p50fix.gateway import attach as _attach_p50_gateway

    def _p50_update(environ):
        try:
            from automation5535.common import load_config as _load_cfg
            from automation5535.store import Store as _OpStore
            _auto_cfg = _Path(__file__).resolve().parent / '5535_automation.json'
            _cfg = _load_cfg(_auto_cfg)
            _store = _OpStore(_cfg['database'])
            _j = _store.latest_job()
            if _j and _j['status'] == 'RUNNING' and _j['heartbeat'] > _time.time() - 120:
                return {'status': 'already_running'}
            def _job():
                try:
                    from automation5535.pipeline import run
                    run(_cfg)
                except Exception:
                    pass
            _threading.Thread(target=_job, daemon=True).start()
            return {'status': 'started',
                    'message': '采集→数据库→研究批处理；P50 serving 需另行 publish 刷新'}
        except Exception as _exc:
            return {'status': 'error', 'error': str(_exc)[:200]}

    _attach_p50_gateway(app, _Path(__file__).resolve().parent / 'p50_config.json',
                        update=_p50_update)
    print('P50 DatabaseOnlyGateway attached (serving layer, SQLITE_ONLY)')
except Exception as _p50_gw_exc:
    print('P50 gateway NOT attached:', _p50_gw_exc)
# END P50 DATABASE-ONLY GATEWAY

# BEGIN 5535 DUAL CHART RECOVERY
# The P50 gateway remains for unrelated views. Charts, replay dates, and the
# update button use the original live database pipeline plus validated SQL history.
try:
    from chart_recovery import attach as _attach_chart_recovery
    _attach_chart_recovery(app, __file__)
except ModuleNotFoundError as _chart_recovery_missing:
    print('chart recovery unavailable; keeping core dashboard routes:', _chart_recovery_missing, flush=True)
# END 5535 DUAL CHART RECOVERY



# BEGIN 5535 COCKPIT FAST 910 HOOK
# Both attach functions are idempotent. Existing automation updater is preserved.
try:
    from chart_recovery import attach as _attach_chart_recovery_for_fast
    _attach_chart_recovery_for_fast(app, __file__)
    from chart_recovery.cockpit_fast import attach as _attach_cockpit_fast
    _attach_cockpit_fast(app, __file__, prewarm=False)
    print("驾驶舱只读预热状态：", getattr(app.wsgi_app, "prewarm_result", {}))
except ModuleNotFoundError as _cockpit_fast_missing:
    print('cockpit fast unavailable; keeping core dashboard routes:', _cockpit_fast_missing, flush=True)
# END 5535 COCKPIT FAST 910 HOOK


# BEGIN 883900 SEMANTIC CACHE HOOK
try:
    from market_speed_883900 import attach as _attach_883900_speed
    _attach_883900_speed(app, __file__)
except ModuleNotFoundError as _market_speed_missing:
    print('semantic cache unavailable; keeping core dashboard routes:', _market_speed_missing, flush=True)
# END 883900 SEMANTIC CACHE HOOK

# BEGIN 5535 BU ROUTE R3
try:
    from bu_route_r3.runtime import attach as _attach_bu_route_r3
    _attach_bu_route_r3(app, __file__, '_5535_runtime/5535_UI_PRESERVED_2_1_8b457d4677495bf3')
except ModuleNotFoundError as _bu_r3_missing:
    print('BU route R3 unavailable:', _bu_r3_missing, flush=True)
# END 5535 BU ROUTE R3

# BEGIN 5535 BU ROUTE R4 PLAN READ
try:
    from bu_route_r4.runtime import attach as _attach_bu_route_r4_plan_read
    _attach_bu_route_r4_plan_read(app, __file__, '_5535_runtime/5535_UI_PRESERVED_2_1_8b457d4677495bf3')
except ModuleNotFoundError as _bu_r4_missing:
    print('BU route R4 unavailable:', _bu_r4_missing, flush=True)
# END 5535 BU ROUTE R4 PLAN READ

# BEGIN 5535 BU ROUTE R5 SINGLE ENTRY
try:
    from bu_route_r5.runtime import attach as _attach_bu_route_r5_single_entry
    _attach_bu_route_r5_single_entry(app, __file__, '_5535_runtime/5535_UI_PRESERVED_2_1_8b457d4677495bf3')
except ModuleNotFoundError as _bu_r5_missing:
    print('BU route R5 unavailable:', _bu_r5_missing, flush=True)
# END 5535 BU ROUTE R5 SINGLE ENTRY

# BEGIN 5535 BU ROUTE R6 PUBLICATION AND SELECTED SCORE GUARD
try:
    from bu_route_r6.runtime import attach as _attach_bu_route_r6
    _attach_bu_route_r6(app, __file__)
except ModuleNotFoundError as _bu_r6_missing:
    print('BU route R6 unavailable:', _bu_r6_missing, flush=True)
# END 5535 BU ROUTE R6 PUBLICATION AND SELECTED SCORE GUARD



@app.route('/api/force-kill-job', methods=['POST'])
def force_kill_job():
    import subprocess
    subprocess.Popen(['taskkill', '/f', '/im', 'python.exe', '/fi', 'PID ne ' + str(__import__('os').getpid())], shell=False)
    return {"ok": True}

if __name__ == '__main__':

    _start_cleanup_scheduler()

    print(
        f"A股打板情绪仪表盘 V{VERSION} Web启动"
    )

    print(
        "浏览器访问: http://127.0.0.1:5000"
    )

    app.run(
        host='0.0.0.0',
        port=5000,
        debug=False
    )
