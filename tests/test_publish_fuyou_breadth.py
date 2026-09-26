import sqlite3

import publish_completed_generation
from publish_completed_generation import _accept_verified_fuyou_breadth, _ensure_published_day


def _inputs():
    return (
        {'date': '20260924'},
        {'input_evidence': {'breadth': {
            'source': 'FUYAO', 'status': 'VALID', 'source_date': '20260924',
            'date_verified': True, 'closing_verified': True, 'complete': True,
            'scope': 'PROVIDER_NATIVE', 'up': 2, 'down': 3, 'flat': 1, 'unknown': 1, 'total': 7,
            'validation_evidence': {'calendar_latest_trading_day': '20260924',
                'event_pool_anchor_check': {'anchor_rows': 3, 'missing': [], 'price_mismatch': [], 'change_mismatch': []}},
        }}},
    )


def test_publish_accepts_only_complete_verified_fuyou_breadth():
    bundle, snapshot = _inputs()
    legacy = {'status': 'DATA_PENDING', 'source_date_verified': True, 'closing_verified': True, 'scope_complete': True}
    result = _accept_verified_fuyou_breadth(legacy, bundle, snapshot)
    assert result['status'] == 'VALID_MARKET_INPUT'
    assert result['breadth_source'] == 'FUYAO'


def test_publish_rejects_fuyou_breadth_with_anchor_mismatch():
    bundle, snapshot = _inputs()
    snapshot['input_evidence']['breadth']['validation_evidence']['event_pool_anchor_check']['price_mismatch'] = ['600001']
    legacy = {'status': 'DATA_PENDING', 'source_date_verified': True, 'closing_verified': True, 'scope_complete': True}
    assert _accept_verified_fuyou_breadth(legacy, bundle, snapshot)['status'] == 'DATA_PENDING'


def test_publish_accepts_verified_receipt_from_input_bundle():
    bundle, snapshot = _inputs()
    receipt = snapshot['input_evidence']['breadth'].pop('validation_evidence')
    bundle['market_breadth'] = {'raw': receipt}
    legacy = {'status': 'DATA_PENDING', 'source_date_verified': True, 'closing_verified': True, 'scope_complete': True}
    assert _accept_verified_fuyou_breadth(legacy, bundle, snapshot)['status'] == 'VALID_MARKET_INPUT'


def test_publish_rejects_mismatched_receipt_from_input_bundle():
    bundle, snapshot = _inputs()
    receipt = snapshot['input_evidence']['breadth'].pop('validation_evidence')
    receipt['event_pool_anchor_check']['missing'] = ['600001']
    bundle['market_breadth'] = {'raw': receipt}
    legacy = {'status': 'DATA_PENDING', 'source_date_verified': True, 'closing_verified': True, 'scope_complete': True}
    assert _accept_verified_fuyou_breadth(legacy, bundle, snapshot)['status'] == 'DATA_PENDING'


def test_published_day_registration_requires_a_verified_batch(monkeypatch):
    connection = sqlite3.connect(':memory:')
    connection.execute('CREATE TABLE batches_fact(id TEXT PRIMARY KEY, quality_status TEXT NOT NULL)')
    connection.execute('CREATE TABLE published_days(trade_date TEXT PRIMARY KEY, batch_id TEXT NOT NULL, first_batch_id TEXT NOT NULL, updated_at TEXT NOT NULL)')
    connection.execute("INSERT INTO batches_fact VALUES('valid', 'VALID_MARKET_INPUT')")
    connection.execute("INSERT INTO batches_fact VALUES('pending', 'DATA_PENDING')")

    class SharedConnection:
        def __enter__(self):
            return connection

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(publish_completed_generation.sqlite3, 'connect', lambda *args, **kwargs: SharedConnection())
    _ensure_published_day('ignored', '20260902', 'valid')

    assert connection.execute('SELECT batch_id,first_batch_id FROM published_days').fetchone() == ('valid', 'valid')
