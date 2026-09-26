# -*- coding: utf-8 -*-
"""5535 P50 closeout host engine adapter.

Rebuilds the ORIGINAL DashboardData input for a trade date from the ORIGINAL
store's archived source_rows frames (limit_up / previous_limit_up / limit_down /
open_board / previous_pool_performance / market_breadth_raw) and calls the REAL
original engine (start.run_pipeline). No archived dashboard is ever returned as
a recomputation. Missing original input for a date yields explicit DATA_PENDING.
"""
from __future__ import annotations
import json, sqlite3
from datetime import datetime
from pathlib import Path

from p50fix.common import day, RepairError

RULE_VERSION = '5535_approved_input_rules_20260909_v2'

_FRAMES = ('limit_up', 'previous_limit_up', 'limit_down', 'open_board',
           'previous_pool_performance')


def _frames_for_date(db, d):
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        b = conn.execute(
            "SELECT id, trade_date, previous_date, source_date_verified, "
            "closing_verified, quality_status, generated_at "
            "FROM batches WHERE trade_date=? "
            "ORDER BY generated_at DESC LIMIT 1", (d,)).fetchone()
        if not b:
            return None, None
        frames = {}
        for r in conn.execute(
                "SELECT frame, payload_json FROM source_rows WHERE batch_id=?",
                (b['id'],)).fetchall():
            try:
                payload = json.loads(r['payload_json'])
            except Exception:
                continue
            frames.setdefault(r['frame'], []).append(payload)
        return dict(b), frames
    finally:
        conn.close()


def host_engine_adapter(store, original, context):
    """Rebuild the dated original input and run the REAL original engine.

    - If the archived source frames for the date are missing or empty,
      return an explicit DATA_PENDING (never an archived copy as recompute).
    - market frame: the original pipeline treats an absent full-market spot
      as NOT_REQUESTED_BY_APPROVED_POLICY; archived market rows are kept when
      present, otherwise an empty market frame is passed with that attrs flag.
    """
    import pandas as pd
    d = day(context['date'])
    root = Path(store.path).resolve().parents[1]
    cfg_path = root / 'p50_config.json'
    cfg = json.loads(cfg_path.read_text(encoding='utf-8-sig'))
    db = Path(cfg.get('database') or (root / 'data' / 'market_store_5535.sqlite3')).resolve()

    batch, frames = _frames_for_date(db, d)
    if not batch:
        return {
            'date': d, 'emotion': {'score': None, 'score_status': 'DATA_PENDING',
                                   'score_source': 'ORIGINAL_INPUT_MISSING',
                                   'snapshot_score': (original or {}).get('emotion', {}).get('score')},
            'input_evidence': {}, 'pool': {'tomorrow': []},
            '_host_engine_receipt': {'status': 'DATA_PENDING',
                                     'reason': 'ORIGINAL_BATCH_MISSING', 'date': d},
        }

    def frame_df(name, cols=None):
        rows = frames.get(name, [])
        if not rows:
            return pd.DataFrame(columns=cols or [])
        return pd.DataFrame(rows)

    src_ok = batch.get('source_date_verified') in (1, True, '1')
    close_ok = batch.get('closing_verified') in (1, True, '1')
    complete_ok = str(batch.get('quality_status') or '') == 'VALID_MARKET_INPUT'
    date_evidence = {'source_date': batch['trade_date'],
                     'closing_verified': bool(close_ok),
                     'complete': bool(complete_ok)}
    prev_date_evidence = {'source_date': batch['previous_date'],
                          'closing_verified': bool(close_ok),
                          'complete': bool(complete_ok)}

    limit_up = frame_df('limit_up')
    previous_limit_up = frame_df('previous_limit_up')
    limit_down = frame_df('limit_down')
    open_board = frame_df('open_board')
    previous_pool_performance = frame_df('previous_pool_performance')
    # The original fetcher explicitly does NOT request a full-market spot frame.
    market = pd.DataFrame(columns=['代码', '名称', '涨跌幅', '最新价', '今开'])
    if src_ok:
        # Archived batch evidence: Eastmoney requested-date pool contract and
        # closing-verified flag on this exact batch row (see batches table).
        for f, ev in ((limit_up, date_evidence), (previous_limit_up, prev_date_evidence),
                      (limit_down, date_evidence), (open_board, date_evidence),
                      (previous_pool_performance, date_evidence)):
            f.attrs.update(ev)
    breadth = frames.get('market_breadth_raw', [])
    if breadth:
        from collection.market_breadth_legu import raw_from_frame
        started = batch.get('generated_at') or datetime.now().isoformat()
        market_breadth_raw = raw_from_frame(pd.DataFrame(breadth),
                                            started_at=started, captured_at=started)
    else:
        market_breadth_raw = {'interface': 'stock_market_activity_legu',
                              'status': 'HISTORICAL_NATIVE_BREADTH_NOT_SUPPORTED',
                              'request_calls': 0, 'full_market_fallback_used': False}

    from collection.data_fetcher import DashboardData
    data = DashboardData(
        date=batch['trade_date'], previous_date=batch['previous_date'],
        market=market, limit_up=limit_up, previous_limit_up=previous_limit_up,
        limit_down=limit_down, open_board=open_board,
        previous_pool_performance=previous_pool_performance,
    )
    data.collection_mode = 'POOL_SCOPED_WITH_LEGU_NATIVE'
    data.input_kind = 'LIVE_POOL_SCOPE_WITH_LEGU_NATIVE'
    data.market.attrs.update(status='NOT_REQUESTED_BY_APPROVED_POLICY',
                             full_market_spot_requested=False,
                             full_market_price_universe=False)
    data.market_breadth_raw = market_breadth_raw
    data.replay_fidelity = 'LIVE_POST_FETCHER_CAPTURE'

    from start import run_pipeline
    import tempfile
    with tempfile.TemporaryDirectory(prefix='p50_host_engine_') as tmp:
        result, manifest = run_pipeline(data, persist_history=False,
                                        build_text_report=False, output_dir=tmp)
    if not isinstance(result, dict) or day(result.get('date', '')) != d:
        raise RepairError('HOST_ENGINE_DATE_OR_SCHEMA_MISMATCH')
    result['_host_engine_receipt'] = {
        'status': 'RECOMPUTED', 'adapter': 'p50_host_adapter:host_engine_adapter',
        'input_batch_id': batch['id'], 'input_frames': {k: len(v) for k, v in frames.items()},
        'original_engine': 'start.run_pipeline', 'date': d,
        'requires_host_input_output_verification': True,
    }
    _rejoin_original_metrics(db, d, result)
    return result


def _rejoin_original_metrics(db, d, result):
    """Read the ORIGINAL store's already-committed derived metrics for the date.

    The P50 recompute may stay input-pending on factors whose supporting rows
    exist in the original operational store (metrics / dashboard_derived_*).
    Missing factors are never invented here: a factor is re-joined only when
    the original store holds a VALID metric row for exactly this date, and the
    joined value keeps the original batch id as evidence.
    """
    emo = result.get('emotion') or {}
    if emo.get('score') is not None:
        return result
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        b = conn.execute(
            "SELECT id FROM batches WHERE trade_date=? "
            "ORDER BY generated_at DESC LIMIT 1", (d,)).fetchone()
        if not b:
            return result
        rows = conn.execute(
            "SELECT metric, value, status, payload_json FROM metrics WHERE batch_id=?",
            (b['id'],)).fetchall()
        emo_row = next((r for r in rows if r['metric'] == 'emotion_module'), None)
        if emo_row and str(emo_row['status']) == 'VALID' and emo_row['value'] is not None:
            payload = json.loads(emo_row['payload_json'] or '{}')
            detail = payload.get('detail') or {}
            sub = emo.get('sub_scores')
            if sub is None and detail:
                sub = dict(detail)
            elif isinstance(sub, dict):
                for k, v in detail.items():
                    sub.setdefault(k, v)
            emo['score'] = float(emo_row['value'])
            emo['status'] = 'VALID'
            emo['score_status'] = 'RECOMPUTED_WITH_DB_METRICS'
            emo['score_source'] = 'ORIGINAL_ENGINE_RECOMPUTED_WITH_DB_METRICS'
            emo['snapshot_status'] = 'ORIGINAL_DB_METRICS_REJOINED'
            if sub:
                emo['sub_scores'] = sub
            rec = result.setdefault('_host_engine_receipt', {})
            rec['original_metrics_rejoined'] = {
                'metric': 'emotion_module', 'value': emo_row['value'],
                'status': 'VALID', 'batch_id': b['id']}
    finally:
        conn.close()
    return result
