"""Private recent-news cache using AIHOT's anonymous, conditional public API."""
from contextlib import contextmanager
from datetime import datetime
from email.utils import parsedate_to_datetime
import gzip
import ipaddress
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MODES = ('selected', 'all')
INTERVAL = 60
LIMIT = 100
MAX_RESPONSE = 2_000_000
ITEM_ID = re.compile(r'[A-Za-z0-9_-]{1,96}')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch_public(url, headers):
    """Only fixed API addresses; verify TLS and bound both compressed and JSON sizes."""
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.netloc != 'aihot.news' or parsed.path != '/api/v1/items':
        raise ValueError('Unknown news endpoint')
    request = Request(url, headers={'Accept': 'application/json', 'Accept-Encoding': 'gzip',
                                   'User-Agent': 'Kindle-Muse-Reader/1.0', **headers})
    try:
        response = build_opener(NoRedirect()).open(request, timeout=25)
    except HTTPError as exc:
        with exc:
            return exc.code, dict(exc.headers), b''
    with response:
        raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError('News response exceeds the size limit')
        if response.headers.get('Content-Encoding') == 'gzip':
            import io
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                raw = stream.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError('News JSON exceeds the size limit')
        return response.status, dict(response.headers), raw


def public_link(value, aihot=False):
    if not isinstance(value, str) or len(value) > 4096:
        return ''
    try:
        link = urlsplit(value)
        host = link.hostname or ''
        if link.scheme not in ('https', 'http') or not host or link.username or link.password:
            return ''
        if aihot and (link.scheme != 'https' or link.netloc != 'aihot.news'):
            return ''
        if host in ('localhost', 'localhost.localdomain') or '.' not in host or host.endswith(('.local', '.internal')):
            return ''
        try:
            if not ipaddress.ip_address(host).is_global:
                return ''
        except ValueError:
            pass
        return value
    except ValueError:
        return ''


def timestamp(value, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise ValueError('Source date is missing')
    date = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if date.tzinfo is None:
        raise ValueError('Source date has no timezone')
    return date.timestamp()


def normalize_items(body):
    data = json.loads(body)
    if not isinstance(data, dict) or not isinstance(data.get('items'), list) or len(data['items']) > LIMIT:
        raise ValueError('Invalid news response')
    result, seen = [], set()
    for row in data['items']:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not ITEM_ID.fullmatch(row['id']):
            raise ValueError('Invalid news identifier')
        if row['id'] in seen:
            raise ValueError('Duplicate news identifier')
        seen.add(row['id'])
        title, summary, reason = row.get('title'), row.get('summary') or '', row.get('reason') or ''
        if not isinstance(title, str) or not title.strip() or len(title) > 2000:
            raise ValueError('Invalid news title')
        if not isinstance(summary, str) or not isinstance(reason, str) or len(summary) + len(reason) > 32_000:
            raise ValueError('Invalid news summary')
        links, source = row.get('links'), row.get('source')
        if not isinstance(links, dict) or not isinstance(source, dict) or not isinstance(source.get('name'), str):
            raise ValueError('Missing news provenance')
        aihot_url = public_link(links.get('aihot'), aihot=True)
        if not aihot_url:
            raise ValueError('Invalid AIHOT reading link')
        result.append({'id': row['id'], 'title': title, 'summary': summary, 'reason': reason,
                       'source': source['name'][:300], 'aihot_url': aihot_url,
                       'category': row.get('category') if isinstance(row.get('category'), str) else '',
                       'original_url': public_link(links.get('original')),
                       'published_at': timestamp(row.get('publishedAt')),
                       'discovered_at': timestamp(row.get('discoveredAt'), required=True),
                       'attribution': {'name': 'AIHOT', 'url': aihot_url}})
    return result


def cache_interval(headers):
    value = headers.get('cache-control', '')
    match = re.search(r'(?:^|,)\s*s-maxage=(\d+)', value) or re.search(r'(?:^|,)\s*max-age=(\d+)', value)
    return max(INTERVAL, int(match.group(1))) if match else INTERVAL


def retry_interval(value, now):
    try:
        return max(INTERVAL, int(value))
    except (TypeError, ValueError):
        try:
            date = parsedate_to_datetime(value)
            return max(INTERVAL, int(date.timestamp() - now))
        except (TypeError, ValueError, OverflowError):
            return INTERVAL


class FeedCache:
    def __init__(self, directory, fetcher=fetch_public, clock=time.time):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / 'aihot.sqlite3'
        self.fetcher, self.clock = fetcher, clock
        self.stop = threading.Event()
        self.thread = None
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS feed_state (
                    mode TEXT PRIMARY KEY, etag TEXT DEFAULT '', last_checked REAL DEFAULT 0,
                    last_success REAL DEFAULT 0, next_check REAL DEFAULT 0, error TEXT DEFAULT '',
                    interval INTEGER DEFAULT 60);
                CREATE TABLE IF NOT EXISTS feed_items (
                    mode TEXT, id TEXT, position INTEGER, data TEXT, PRIMARY KEY(mode,id));
            ''')
            for mode in MODES:
                db.execute('INSERT OR IGNORE INTO feed_state(mode) VALUES (?)', (mode,))
            # Earlier JSON cache omitted source categories; fetch a fresh snapshot once.
            if db.execute('PRAGMA user_version').fetchone()[0] < 1:
                db.execute("UPDATE feed_state SET etag='',next_check=0")
                db.execute('PRAGMA user_version=1')
        self.path.chmod(0o600)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def status(self, mode='selected'):
        if mode not in MODES:
            raise ValueError('Unknown news mode')
        with self.db() as db:
            state = dict(db.execute('SELECT * FROM feed_state WHERE mode=?', (mode,)).fetchone())
            state['count'] = db.execute('SELECT count(*) FROM feed_items WHERE mode=?', (mode,)).fetchone()[0]
        return state

    def items(self, mode='selected', offset=0, limit=10):
        if mode not in MODES:
            raise ValueError('Unknown news mode')
        with self.db() as db:
            rows = db.execute('SELECT data FROM feed_items WHERE mode=? ORDER BY position LIMIT ? OFFSET ?',
                              (mode, limit, offset)).fetchall()
        return [json.loads(row['data']) for row in rows]

    def get(self, ident, mode='selected'):
        if mode not in MODES or not ITEM_ID.fullmatch(ident):
            return None
        with self.db() as db:
            row = db.execute('SELECT data FROM feed_items WHERE mode=? AND id=?', (mode, ident)).fetchone()
        return json.loads(row['data']) if row else None

    def sync(self, mode):
        state, now = self.status(mode), self.clock()
        url = 'https://aihot.news/api/v1/items?' + urlencode({'mode': mode, 'window': '7d', 'by': 'timeline', 'limit': LIMIT})
        request_headers = {'If-None-Match': state['etag']} if state['etag'] else {}
        delay = INTERVAL
        try:
            code, headers, body = self.fetcher(url, request_headers)
            headers = {key.lower(): value for key, value in headers.items()}
            delay = cache_interval(headers)
            if code not in (200, 304):
                delay = max(delay, retry_interval(headers.get('retry-after'), now))
                raise ValueError(f'资讯源 HTTP {code}，稍后自动重试。')
            if code == 304:
                if not state['last_success']:
                    raise ValueError('资讯源尚未返回有效内容。')
                items = None
            else:
                items = normalize_items(body)
            with self.db() as db:
                if items is not None:
                    db.execute('DELETE FROM feed_items WHERE mode=?', (mode,))
                    db.executemany('INSERT INTO feed_items VALUES (?,?,?,?)',
                                   [(mode, row['id'], i, json.dumps(row, ensure_ascii=False)) for i, row in enumerate(items)])
                db.execute('UPDATE feed_state SET etag=?,last_checked=?,last_success=?,next_check=?,error=?,interval=? WHERE mode=?',
                           (headers.get('etag', state['etag']), now, now, now + delay, '', delay, mode))
            return {'ok': True, 'http_status': code, 'count': self.status(mode)['count']}
        except (OSError, ValueError, TypeError, KeyError) as exc:
            error = str(exc) if str(exc).startswith('资讯源 ') else '资讯同步暂不可用，保留上次成功同步的内容。'
            with self.db() as db:
                db.execute('UPDATE feed_state SET last_checked=?,next_check=?,error=? WHERE mode=?',
                           (now, now + delay, error, mode))
            return {'ok': False, 'http_status': None, 'count': state['count']}

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        def run():
            while not self.stop.is_set():
                for mode in MODES:
                    if self.stop.is_set():
                        break
                    if self.clock() >= self.status(mode)['next_check']:
                        self.sync(mode)
                self.stop.wait(1)
        self.thread = threading.Thread(target=run, name='aihot-news-sync', daemon=True)
        self.thread.start()
