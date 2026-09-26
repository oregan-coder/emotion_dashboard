# -*- coding: utf-8 -*-
"""Read-only web projection of the original dashboard snapshot.

Preserve unknown/extension fields, including policy evidence and provenance.
Never recalculate a score, infer a market value or rewrite source/history files.
"""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
import pandas as pd
from config import SMASH_HISTORY_FILE
from history_manager import load_history
from input_contracts import clean_json

DASHBOARD_FILE = Path(__file__).parent / 'data' / 'dashboard.json'


def default_dashboard():
    """Structural defaults only: absent numeric evidence is null, not zero."""
    return {
        'date': '', 'previous_date': '', 'update_time': '',
        'market': {'up': None, 'down': None, 'flat': None},
        'limit': {'up': None, 'prev_up': None, 'down': None, 'prev_down': None, 'seal_rate': None},
        'emotion': {'score': None, 'cycle_stage': '', 'height_stage': '', 'detail': {}},
        'smash': {'score': None, 'status': '', 'highest_board': None, 'leader': '',
                  'break_rate': None, 'high_feedback': '', 'high_count': None,
                  'high_continue_count': None, 'high_break_count': None,
                  'rates': {k: None for k in ('rate12', 'rate23', 'rate34', 'rate45', 'rate56')}},
        'ladder': [], 'cycle': {'emotion_cycle': None, 'height_cycle': None,
            'comprehensive': None, 'stage': None, 'trend': None, 'description': ''},
        'position': {'suggest': None, 'risk': None, 'strategy': None},
        'history': [], 'smash_history': [],
        'pool': {'second_board': [], 'first_board': [], 'tomorrow': []},
        'leader': {'highest': {}, 'high_boards': [], 'ladder_detail': {}, 'high_break': [],
            'signals': {'highest_break': None, 'high_break_rate': None,
                        'ladder_gap': None, 'gap_detail': '', 'risk_level': None, 'risk_desc': ''}},
    }


def _merge(base, extra):
    """Source values win, including explicit null; don't whitelist away new fields."""
    result = deepcopy(base)
    if not isinstance(extra, dict):
        return result
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _clean(value):
    """Strict JSON with non-finite numeric/missing values kept as null."""
    return clean_json(value)


def load_dashboard_json():
    """Read a snapshot; errors remain explicit rather than making a zero market."""
    try:
        with open(DASHBOARD_FILE, encoding='utf-8-sig') as stream:
            obj = json.load(stream, parse_constant=lambda _: None)
        if not isinstance(obj, dict):
            raise ValueError('Snapshot JSON root must be an object')
        return obj
    except FileNotFoundError:
        return {'snapshot_read': {'status': 'MISSING', 'error_type': 'SNAPSHOT_MISSING'}, 'date': ''}
    except (ValueError, OSError, UnicodeError) as exc:
        return {'snapshot_read': {'status': 'ERROR', 'error_type': type(exc).__name__, 'error': str(exc)}, 'date': ''}


def load_smash_history(days=20):
    """Read existing CSV only. Missing observations must remain gaps in the chart."""
    try:
        df = pd.read_csv(SMASH_HISTORY_FILE, dtype={'date': str})
    except (OSError, ValueError, pd.errors.ParserError):
        return []
    if df is None or df.empty:
        return []
    for col in ('smash_score', 'highest_board', 'rate_23', 'rate_34', 'rate_45', 'rate_56'):
        if col in df:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    if 'date' in df:
        df['date'] = df['date'].astype(str).str.replace('.0', '', regex=False)
    return _clean(df.tail(days).to_dict('records'))


def build_dashboard():
    dashboard = load_dashboard_json()
    result = _merge(default_dashboard(), dashboard)
    # Compatibility aliases only; do not replace an explicitly-null new field.
    cycle = result.get('cycle')
    original_cycle = dashboard.get('cycle')
    if isinstance(cycle, dict) and isinstance(original_cycle, dict):
        if 'height_cycle' not in original_cycle and original_cycle.get('space_cycle'):
            cycle['height_cycle'] = original_cycle['space_cycle']
        if 'comprehensive' not in original_cycle and original_cycle.get('conclusion'):
            cycle['comprehensive'] = original_cycle['conclusion']
    try:
        history = load_history()
        if hasattr(history, 'to_dict') and len(history):
            records = history.to_dict('records')
            target = str(result.get('date') or '')
            if target:
                records = [r for r in records if str(r.get('date', '')).replace('-', '') <= target]
            result['history'] = records[-5:]
    except Exception as exc:
        result.setdefault('serving_warnings', []).append({'component': 'history', 'error_type': type(exc).__name__})
    try:
        records = load_smash_history(200)
        if records:
            target = str(result.get('date') or '')
            result['smash_history'] = [r for r in records if not target or str(r.get('date', '')).replace('-', '') <= target]
    except Exception as exc:
        result.setdefault('serving_warnings', []).append({'component': 'smash_history', 'error_type': type(exc).__name__})
    return _clean(result)
