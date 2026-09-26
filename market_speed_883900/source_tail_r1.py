"""Bounded, unauthenticated 883900-only worker. Never opens a database."""
from __future__ import annotations
import contextlib
import datetime as dt
import io
import json
import re
import sys
import time
from . import common as C
from .freshness_r1 import TailError, calendar_days


class Restricted(TailError):
    pass


class Wire:
    def __init__(self, budget=55):
        import requests
        self.session = requests.Session()
        self.session.trust_env = False  # No netrc/auth cookies from the environment.
        self.deadline = time.monotonic()+budget
        self.events = []

    def get(self, url, **kwargs):
        if time.monotonic() >= self.deadline:
            raise TailError('SOURCE_WALL_BUDGET_EXHAUSTED')
        if len(self.events) >= 5:
            raise TailError('MAX_FIVE_PUBLIC_REQUESTS')
        if not (url == 'https://finance.sina.com.cn/realstock/company/klc_td_sh.txt'
                or re.fullmatch(r'https://d\.10jqka\.com\.cn/v[46]/line/(bk|48)_883900/01/(last|\d{4})\.js', url)
                or url == 'https://d.10jqka.com.cn/v6/realhead/48_883900/last.js'):
            raise TailError('OUT_OF_SCOPE_URL')
        remaining = self.deadline-time.monotonic()
        if remaining < 1:
            raise TailError('SOURCE_WALL_BUDGET_EXHAUSTED')
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://q.10jqka.com.cn/'}
        if '/realhead/' in url:
            headers = {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15', 'Referer': 'https://m.10jqka.com.cn/'}
        event = {'url': url, 'requested_at': C.now_iso(), 'cookie_or_token_used': False}
        self.events.append(event)
        started = time.monotonic()
        try:
            self.session.cookies.clear()
            response = self.session.get(url, headers=headers, timeout=(min(3.05, remaining), min(6, remaining)), allow_redirects=False, stream=True)
            chunks, size = [], 0
            try:
                for chunk in response.iter_content(64*1024):
                    if time.monotonic() >= self.deadline:
                        raise TailError('SOURCE_STREAM_DEADLINE')
                    size += len(chunk)
                    if size > 2*1024*1024:
                        raise TailError('SOURCE_BODY_TOO_LARGE')
                    chunks.append(chunk)
            finally:
                response.close()
            response._content = b''.join(chunks)
            response._content_consumed = True
            response.encoding = response.encoding or 'utf-8'
            if response.encoding.lower() == 'iso-8859-1':
                response.encoding = 'utf-8'
            event.update(http_status=response.status_code, raw_text=response.text, raw_sha256=C.digest(response.content),
                         headers={k:v for k,v in response.headers.items() if k.lower() in ('date','last-modified','age','content-type','etag')})
            if response.status_code in (401, 403, 429):
                raise Restricted('SOURCE_ACCESS_RESTRICTED:' + str(response.status_code))
            if 300 <= response.status_code < 400:
                raise TailError('REDIRECT_NOT_FOLLOWED')
            response.raise_for_status()
            return response
        except Exception as exc:
            event.update(error_type=type(exc).__name__, error=str(exc)[:300])
            raise
        finally:
            event['elapsed_seconds'] = round(time.monotonic()-started, 3)

    def close(self):
        self.session.close()


def fetch_calendar(wire):
    """Run the already-installed AKShare decoder with raw HTTP capture and bounds."""
    import requests
    import akshare as ak
    original = requests.get
    def one_calendar_get(url, **kwargs):
        if url != 'https://finance.sina.com.cn/realstock/company/klc_td_sh.txt':
            raise TailError('CALENDAR_FUNCTION_CHANGED_URL')
        return wire.get(url)
    requests.get = one_calendar_get
    try:
        frame = ak.tool_trade_date_hist_sina()
    finally:
        requests.get = original
    if 'trade_date' not in frame.columns:
        raise TailError('CALENDAR_COLUMN_CHANGED')
    days = sorted(set(d for x in frame['trade_date'] if (d := C.day(str(x)))))
    if not days:
        raise TailError('EMPTY_CALENDAR')
    event = next((e for e in reversed(wire.events) if 'klc_td_sh.txt' in e['url']), None)
    if not event or event.get('http_status') != 200:
        raise TailError('CALENDAR_RAW_EVIDENCE_MISSING')
    return {'status': 'VALID', 'verified': True, 'days': days, 'source': 'AKSHARE_SINA_NATIVE_CALENDAR',
            'akshare_version': getattr(ak, '__version__', None), 'raw_evidence': event}


def parse_realhead(text, end, observed_now):
    """Retain existing field mapping; add source time and exact-day close checks."""
    from .index_source import json_object
    obj, _ = json_object(text)
    items = obj.get('items') or {}
    if str(items.get('5', '')).strip() != C.CODE:
        raise TailError('REALHEAD_CODE_MISMATCH')
    raw = str(items.get('updateTime') or items.get('time') or '').strip()
    stamp = None
    if re.fullmatch(r'\d{14}', raw):
        stamp = dt.datetime.strptime(raw, '%Y%m%d%H%M%S')
    else:
        try:
            stamp = dt.datetime.fromisoformat(raw.replace('Z', '+00:00'))
        except ValueError:
            pass
    if stamp is None or len(raw) < 14:
        raise TailError('REALHEAD_NATIVE_CLOSE_TIME_MISSING')
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone(dt.timezone(dt.timedelta(hours=8)))
    if stamp.strftime('%Y%m%d') != end or end != observed_now.strftime('%Y%m%d'):
        raise TailError('REALHEAD_NOT_REQUESTED_TODAY')
    if (observed_now.hour, observed_now.minute) < (15,30) or (stamp.hour,stamp.minute) < (15,0):
        raise TailError('REALHEAD_INTRADAY_NOT_FINAL_CLOSE')
    if stamp.replace(tzinfo=None) > observed_now.replace(tzinfo=None)+dt.timedelta(minutes=2):
        raise TailError('REALHEAD_FUTURE_TIMESTAMP')
    return {'date': end, 'open': C.number(items.get('7')), 'high': C.number(items.get('8')), 'low': C.number(items.get('9')),
            'close': C.number(items.get('10')), 'pre_close': C.number(items.get('6')),
            'pct_change': C.number(items.get('199112')), 'native_time': raw}


def merge_bars(existing, additions):
    for row in additions:
        d = C.day(row.get('date') or row.get('trade_date') or row.get('日期'))
        if not d:
            raise TailError('BAR_NATIVE_DATE_MISSING')
        row = dict(row, date=d)
        if d in existing:
            for key in ('open','high','low','close'):
                x, y = C.number(existing[d].get(key)), C.number(row.get(key))
                if x is not None and y is not None and abs(x-y) > .011:
                    raise TailError('SAME_DAY_PROVIDER_CONFLICT:' + d)
        else:
            existing[d] = row


def collect(config, wire=None, calendar_fetch=None, now=None):
    from .index_source import parse_ths, normalize
    own = wire is None
    wire = wire or Wire(min(55, config.get('wall_budget_seconds',55)))
    now = now or C.china_now()
    result = {'ok': False, 'status': 'PENDING'}
    try:
        requested = config['requested_end']
        ceiling = now.strftime('%Y%m%d') if (now.hour,now.minute)>=(15,30) else (now-dt.timedelta(days=1)).strftime('%Y%m%d')
        if C.day(requested) != requested or requested > ceiling:
            raise TailError('REQUEST_NOT_FINALIZED')
        cal = (calendar_fetch or fetch_calendar)(wire) if config.get('fetch_calendar') else config['calendar']
        days = calendar_days(cal)
        if not days or max(days) < requested:
            raise TailError('CALENDAR_STILL_BEHIND_REQUEST_NO_OLD_DAY_SUCCESS')
        end = max((d for d in days if d <= requested), default=None)
        if not end or (config.get('explicit_end') and end != requested):
            raise TailError('REQUEST_IS_NOT_VERIFIED_TRADING_DAY')
        endpos = days.index(end)
        # 8 target sessions plus 4 warmup sessions plus one prior close.
        prepos = max(0,endpos-12)
        start = days[prepos]
        targets = [d for d in days[max(0,endpos-7):endpos+1] if d >= (C.day(config.get('start')) or start)]
        if not targets:
            raise TailError('EMPTY_TARGET_SCOPE')
        bars, identities = {}, []
        urls = [
            'https://d.10jqka.com.cn/v4/line/bk_883900/01/last.js',
            'https://d.10jqka.com.cn/v6/line/48_883900/01/last.js',
            f'https://d.10jqka.com.cn/v6/line/48_883900/01/{end[:4]}.js',
        ]
        for url in urls:
            try:
                response = wire.get(url)
                parsed = parse_ths(response.text, url)
                merge_bars(bars, parsed['rows'])
                identities.append(parsed['identity_proof'])
                if all(d in bars for d in days[prepos:endpos+1]):
                    break
            except Restricted:
                raise
            except TailError as exc:
                if 'CONFLICT' in str(exc):
                    raise
                wire.events[-1]['parse_error'] = str(exc)
            except Exception as exc:
                wire.events[-1]['parse_error'] = str(exc)[:300]
        if end not in bars and end == now.strftime('%Y%m%d'):
            url = 'https://d.10jqka.com.cn/v6/realhead/48_883900/last.js'
            try:
                response = wire.get(url)
                row = parse_realhead(response.text,end,now)
                merge_bars(bars,[row])
                identities.append({'native_code': C.CODE,'native_time': row['native_time'], 'source': url})
            except Restricted:
                raise
            except Exception as exc:
                wire.events[-1]['parse_error'] = str(exc)[:300]
        # All inputs are captured together. Original code discarded realhead raw
        # text when supplementing a line response; this worker retains both.
        raw = C.dumps({'policy': 'M8839_TAIL_FRESHNESS_R1', 'http_evidence': wire.events})
        source = {'code': C.CODE, 'name': C.NAME, 'rows': list(bars.values()), 'identity_proof': identities}
        normalized = normalize(source,days,start,end,raw,'THS_WEB_MULTI_RESPONSE','https://d.10jqka.com.cn/')
        normalized['response']['metadata'].update(observed_now=now.isoformat(), target_dates=targets, native_finalization_policy='DAILY_KLINE_AFTER_1530_OR_SAME_DAY_REALHEAD_AFTER_1500')
        result.update(ok=True,status='SOURCE_VALIDATED',calendar=cal,end=end,bundle=normalized)
        return result
    except Restricted as exc:
        result.update(status='SOURCE_ACCESS_RESTRICTED',restricted=True,error=str(exc))
        return result
    except Exception as exc:
        result.update(status='SOURCE_OR_CALENDAR_PENDING',error_type=type(exc).__name__,error=str(exc)[:800])
        return result
    finally:
        result['requests'] = len(wire.events)
        result['http_evidence'] = wire.events
        if own:
            wire.close()


def main():
    try:
        config = json.loads(sys.stdin.read())
        # Installed SDKs occasionally print diagnostics. Keep protocol stdout JSON-only.
        with contextlib.redirect_stdout(sys.stderr):
            result = collect(config)
    except Exception as exc:
        result = {'ok':False,'status':'WORKER_ERROR','error_type':type(exc).__name__,'error':str(exc)[:800]}
    print(C.dumps(result),flush=True)
    return 0 if result.get('ok') else 2

if __name__ == '__main__':
    raise SystemExit(main())
