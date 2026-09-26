"""5535: scalar/JSON contracts. No imputation, calibration or trading rules."""
from __future__ import annotations
import math
import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import numpy as np


def number(value, *, minimum=None, maximum=None):
    if value is None or isinstance(value, (bool, np.bool_)):
        return None
    if isinstance(value, (list, tuple, dict, set, np.ndarray)):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(result):
        return None
    if minimum is not None and result < minimum:
        return None
    if maximum is not None and result > maximum:
        return None
    return result


def integer(value, *, minimum=None, maximum=None):
    result = number(value, minimum=minimum, maximum=maximum)
    return int(result) if result is not None and result.is_integer() else None


def boolean(value):
    """Only explicit booleans. String 'False' is not True; numeric 1 is not proof."""
    return bool(value) if isinstance(value, (bool, np.bool_)) else None


def price(value):
    if isinstance(value, (bool, np.bool_)):
        return None, 'INVALID_BOOL'
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, 'MISSING'
    try:
        if not math.isfinite(float(value)):
            return None, 'INVALID_NON_FINITE'
    except (ValueError, TypeError, OverflowError):
        return None, 'INVALID_PARSE_ERROR'
    result = number(value)
    if result is None:
        return None, 'INVALID_PARSE_ERROR'
    return (result, 'VALID') if result > 0 else (None, 'INVALID_NON_POSITIVE')


def normalize_code(value):
    if isinstance(value, (bool, np.bool_)) or value is None:
        return ''
    if isinstance(value, (int, np.integer)):
        s = str(int(value)).zfill(6)
    elif isinstance(value, (float, np.floating)):
        n = integer(value, minimum=0, maximum=999999)
        s = str(n).zfill(6) if n is not None else ''
    else:
        s = str(value).strip().upper()
        s = re.sub(r'^(SH|SZ|BJ)', '', s)
        s = re.sub(r'\.(SH|SZ|BJ)$', '', s)
        if re.fullmatch(r'\d{1,6}\.0', s):
            s = s[:-2]
        if s.isdigit():
            s = s.zfill(6)
    return s if re.fullmatch(r'\d{6}', s) else ''


def find_column(frame, names):
    columns = getattr(frame, 'columns', ())
    return next((n for n in names if n in columns), None)


def board_count(value):
    n = integer(value, minimum=1)
    if n is not None:
        return n
    # 'N天M板' is not consecutive M boards. Require an explicit consecutive field.
    if isinstance(value, str):
        match = re.fullmatch(r'\s*(\d+)连板\s*', value)
        if match:
            return integer(match.group(1), minimum=1)
    return None


def clean_json(value):
    """Strict JSON: unknown non-finite scalars -> null; never NaN/Infinity tokens."""
    import pandas as pd
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, Mapping):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [clean_json(v) for v in value]
    if isinstance(value, np.generic):
        return clean_json(value.item())
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        return clean_json(float(value))
    if isinstance(value, (date, datetime, Path)):
        return str(value)
    if value is None or isinstance(value, (str, int, bool)):
        return value
    # pandas NA/NaT and other explicit scalar missing objects
    try:
        import pandas as pd
        if pd.isna(value) is True:
            return None
    except (TypeError, ValueError):
        pass
    raise TypeError(f'Unsupported JSON type: {type(value).__name__}')
