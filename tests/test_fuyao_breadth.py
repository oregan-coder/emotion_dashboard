from datetime import datetime, timezone, timedelta

from collection.market_breadth_legu import parse_native
from collection.market_breadth_legu import _snapshot_anchor_check
import pandas as pd


def test_parse_native_accepts_complete_fuyou_historical_aggregate():
    raw = {
        'source': 'FUYAO', 'status': 'VALID', 'source_date': '20260902',
        'date_verified': True, 'closing_verified': True, 'complete': True,
        'up': 2, 'down': 3, 'flat': 1, 'unknown': 1, 'total': 7,
        'as_of': datetime.now(timezone(timedelta(hours=8))).isoformat(),
    }
    result = parse_native(raw, '20260902', {'verified': True, 'dates': ['20260901', '20260902']})
    assert result['status'] == 'VALID'
    assert result['total'] == 7
    assert result['unknown'] == 1


def test_parse_native_rejects_fuyou_total_mismatch():
    raw = {
        'source': 'FUYAO', 'status': 'VALID', 'source_date': '20260902',
        'date_verified': True, 'closing_verified': True, 'complete': True,
        'up': 2, 'down': 3, 'flat': 1, 'unknown': 1, 'total': 6,
    }
    result = parse_native(raw, '20260902', {'verified': True, 'dates': ['20260902']})
    assert result['status'] == 'DATA_PENDING'
    assert 'FUYAO_COUNT_TOTAL_MISMATCH' in result['issues']


def test_snapshot_anchor_check_requires_every_event_pool_value_to_match():
    frame = pd.DataFrame([{'代码': '600001', '最新价': 10, '涨跌幅': 1.25}])
    ok, evidence = _snapshot_anchor_check([{'ticker': '600001', 'last_price': 10, 'price_change_ratio_pct': 1.25}], [frame])
    assert ok is True
    assert evidence['anchor_rows'] == 1
    ok, evidence = _snapshot_anchor_check([{'ticker': '600001', 'last_price': 10.1, 'price_change_ratio_pct': 1.25}], [frame])
    assert ok is False
    assert evidence['price_mismatch'] == ['600001']
