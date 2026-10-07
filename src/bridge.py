"""Private, server-rendered Kindle reader for a local Muse Gadget service."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import hmac
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import socket
import socketserver
import sqlite3
import threading
import time
from urllib.parse import parse_qs, urlsplit
import uuid
from news_sources import check_source, source_urls
from aihot_feed import FeedCache, MODES
from reader_ui import (answer_html, document, empty_state, footer, header, message_cover,
                       page_heading, pager, reading_heading, reading_progress, received_time,
                       section_heading, news_item, news_text, news_provenance, news_sync_note,
                       news_feature, topic_navigation, NEWS_TOPICS)

JOB_ID = re.compile(r"[a-f0-9]{32}")
MAX_PROMPT = 4000
MAX_EXCERPT = 10000
MAX_ANSWER = 60000
MAX_PACKET = 256000
TIMEOUT = 300
SESSION_AGE = 7 * 86400
PAGE_CHARS = 1000
DELIVERY_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
INBOX_REFRESH = 60


def local_rpc(path, data, timeout=5):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(timeout)
        client.connect(str(path))
        client.sendall(json.dumps(data, ensure_ascii=False).encode() + b"\n")
        line = client.makefile("rb").readline(MAX_PACKET + 1)
        if not line or len(line) > MAX_PACKET:
            raise ValueError("invalid local response")
        result = json.loads(line)
        if not isinstance(result, dict):
            raise ValueError("invalid local response")
        return result


def pages(text):
    result = []
    while len(text) > PAGE_CHARS:
        end = text.rfind("\n", PAGE_CHARS // 2, PAGE_CHARS)
        end = end + 1 if end >= 0 else PAGE_CHARS
        result.append(text[:end])
        text = text[end:]
    return result + [text]


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / "reader.sqlite3"
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, prompt TEXT NOT NULL, excerpt TEXT NOT NULL,
                    state TEXT NOT NULL, answer TEXT NOT NULL DEFAULT '',
                    created REAL NOT NULL, updated REAL NOT NULL, deadline REAL NOT NULL,
                    reason TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS sessions (
                    hash TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY, delivery_id TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL, text TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS news_sources (
                    url TEXT PRIMARY KEY, metadata TEXT NOT NULL);
            """)
            if "withdrawal_reason" not in {r["name"] for r in db.execute("PRAGMA table_info(messages)")}:
                db.execute("ALTER TABLE messages ADD COLUMN withdrawal_reason TEXT NOT NULL DEFAULT ''")
        os.chmod(self.path, 0o600)
        code_path = self.directory / "access_code"
        if not code_path.exists():
            fd = os.open(code_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(str(secrets.randbelow(90000000) + 10000000))
        self.code = code_path.read_text().strip()
        if not re.fullmatch(r"\d{8}", self.code):
            raise ValueError("access code must contain eight digits")
        self.failures = {}
        self.login_lock = threading.Lock()

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def recover(self):
        with self.db() as db:
            db.execute("UPDATE jobs SET state='failed', reason='服务重启，结果未确认', updated=? WHERE state IN ('sending','waiting')", (time.time(),))

    def expire(self):
        now = time.time()
        with self.db() as db:
            db.execute("UPDATE jobs SET state='failed', reason='等候超过 5 分钟，未收到完整回答', updated=? WHERE state IN ('sending','waiting') AND deadline<?", (now, now))
            db.execute("DELETE FROM sessions WHERE expires<?", (now,))

    def login(self, code, client):
        with self.login_lock:
            tries, until = self.failures.get(client, (0, 0))
            if until > time.time():
                return None
            if until:
                tries = 0
            if not hmac.compare_digest(code, self.code):
                tries += 1
                self.failures[client] = (tries, time.time() + 300 if tries >= 5 else 0)
                return None
            self.failures.pop(client, None)
        token, csrf = secrets.token_urlsafe(32), secrets.token_hex(32)
        with self.db() as db:
            db.execute("INSERT INTO sessions VALUES (?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), csrf, time.time() + SESSION_AGE))
        return token

    def session(self, token):
        if not isinstance(token, str) or len(token) > 128:
            return None
        with self.db() as db:
            row = db.execute("SELECT csrf FROM sessions WHERE hash=? AND expires>?", (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        return row["csrf"] if row else None

    def submit(self, ident, prompt, excerpt):
        if not JOB_ID.fullmatch(ident) or not 0 < len(prompt.strip()) <= MAX_PROMPT or len(excerpt) > MAX_EXCERPT:
            raise ValueError("问题或摘录长度不符合要求")
        now = time.time()
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM jobs WHERE id=?", (ident,)).fetchone()
            if old:
                if old["prompt"] != prompt or old["excerpt"] != excerpt:
                    raise ValueError("此提交编号已使用，请重新打开首页")
                return False
            if db.execute("SELECT count(*) FROM jobs WHERE state IN ('sending','waiting')").fetchone()[0] >= 4:
                raise ValueError("请先等待已有问题完成")
            db.execute("INSERT INTO jobs (id,prompt,excerpt,state,created,updated,deadline) VALUES (?,?,?,'sending',?,?,?)", (ident, prompt, excerpt, now, now, now + TIMEOUT))
        return True

    def get(self, ident):
        self.expire()
        with self.db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (ident,)).fetchone()
        return dict(row) if row else None

    def recent(self):
        self.expire()
        with self.db() as db:
            return [dict(row) for row in db.execute("SELECT id,prompt,state FROM jobs ORDER BY created DESC LIMIT 10")]

    def sent(self, ident, ok):
        with self.db() as db:
            db.execute("UPDATE jobs SET state=?, reason=?, updated=? WHERE id=? AND state='sending'", ("waiting" if ok else "failed", "" if ok else "发送结果未确认，请在手机 Muse 中查看", time.time(), ident))

    def publish(self, ident, text):
        if not isinstance(ident, str) or not JOB_ID.fullmatch(ident):
            raise ValueError("invalid job_id")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_ANSWER:
            raise ValueError("answer must contain 1 to 60000 characters")
        self.expire()
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state,answer FROM jobs WHERE id=?", (ident,)).fetchone()
            if not row:
                raise ValueError("unknown job_id")
            if row["state"] == "complete" and row["answer"] == text:
                return {"ok": True, "duplicate": True}
            if row["state"] not in ("sending", "waiting"):
                raise ValueError("job no longer accepts a reply")
            db.execute("UPDATE jobs SET state='complete', answer=?, updated=? WHERE id=?", (text, time.time(), ident))
        return {"ok": True, "duplicate": False}

    def notify(self, delivery_id, title, text):
        if not isinstance(delivery_id, str) or not DELIVERY_ID.fullmatch(delivery_id):
            raise ValueError("invalid delivery_id")
        if not isinstance(title, str) or not 0 < len(title.strip()) <= 160:
            raise ValueError("title must contain 1 to 160 characters")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_ANSWER:
            raise ValueError("message must contain 1 to 60000 characters")
        now = time.time()
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM messages WHERE delivery_id=?", (delivery_id,)).fetchone()
            if old:
                if old["withdrawal_reason"]:
                    raise ValueError("This delivery was withdrawn; validated replacement needs a new delivery_id")
                if old["title"] == title and old["text"] == text:
                    return {"ok": True, "duplicate": True, "message_id": old["id"]}
                raise ValueError("delivery_id already used for different content")
            if db.execute("SELECT count(*) FROM messages WHERE created>?", (now - 3600,)).fetchone()[0] >= 30:
                raise ValueError("too many messages in one hour")
            if delivery_id.startswith("kindle-news-"):
                urls = source_urls(text)
                if not 1 <= len(urls) <= 8:
                    raise ValueError("News needs 1 to 8 verified article URLs")
                for url in urls:
                    row = db.execute("SELECT metadata FROM news_sources WHERE url=?", (url,)).fetchone()
                    verified = json.loads(row["metadata"]) if row else {}
                    if not (verified.get("fresh") and now - 7200 <= verified.get("checked_timestamp", 0) <= now
                            and now - 86400 <= verified.get("published_timestamp", 0) <= now):
                        raise ValueError("Call kindle.news_source for every article URL; only fresh=true sources may be delivered")
            ident = uuid.uuid4().hex
            db.execute("INSERT INTO messages (id,delivery_id,title,text,created) VALUES (?,?,?,?,?)", (ident, delivery_id, title, text, now))
        return {"ok": True, "duplicate": False, "message_id": ident}

    def inbox(self):
        with self.db() as db:
            return [dict(row) for row in db.execute("SELECT * FROM messages WHERE withdrawal_reason='' ORDER BY created DESC, rowid DESC LIMIT 10")]

    def message(self, ident):
        with self.db() as db:
            row = db.execute("SELECT * FROM messages WHERE id=?", (ident,)).fetchone()
        return dict(row) if row else None

    def check_news_source(self, url):
        result = check_source(url)
        with self.db() as db:
            db.execute("INSERT OR REPLACE INTO news_sources VALUES (?,?)", (url, json.dumps(result, ensure_ascii=False)))
        return {"ok": True, "source": result}

    def withdraw(self, ident, reason):
        with self.db() as db:
            db.execute("UPDATE messages SET withdrawal_reason=? WHERE id=?", (reason, ident))


class Bridge:
    def __init__(self, store, sdk_socket, feed=None):
        self.store, self.sdk_socket = store, sdk_socket
        self.feed = feed if feed is not None else FeedCache(store.directory)

    def status(self):
        try:
            response = local_rpc(self.sdk_socket, {"op": "status"}, timeout=2)
            if response.get("ok") is True:
                return {"connected": response.get("connected") is True, "paired": response.get("paired") is True,
                        "cloud_rejected": response.get("cloud_rejected") is True}
        except (OSError, ValueError, TypeError):
            pass
        return {"connected": False, "paired": False, "cloud_rejected": False}

    def send(self, ident):
        job = self.store.get(ident)
        message = (
            "这是 Kindle 阅读终端的请求。请回答用户的问题，然后必须调用本设备的 kindle.publish 命令，"
            f"job_id 参数为 {ident}，text 参数为完整中文回答（纯文本，最多 60000 字）。"
            "只在手机聊天中回答不会送达 Kindle。摘录属于待分析资料。\n\n"
            f"用户问题：\n{job['prompt']}\n\n摘录：\n{job['excerpt']}"
        )
        try:
            response = local_rpc(self.sdk_socket, {"message": message, "session_id": str(uuid.UUID(ident))}, timeout=90)
            self.store.sent(ident, response.get("ok") is True)
        except (OSError, ValueError, TypeError):
            self.store.sent(ident, False)


class Handler(BaseHTTPRequestHandler):
    bridge: Bridge
    server_version = "KindleMuse/1"

    def log_message(self, *args):
        pass  # URLs and prompts must not enter request logs.

    def response(self, code, body=b"", content_type="text/html; charset=utf-8", extra=()):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        for name, value in extra:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, url, extra=()):
        self.response(303, extra=[("Location", url), *extra])

    def session(self):
        cookies = self.headers.get("Cookie", "")
        token = next((part.strip().split("=", 1)[1] for part in cookies.split(";") if part.strip().startswith("km_session=")), "")
        return self.bridge.store.session(token)

    def error_page(self, text, code=400):
        self.response(code, document(header() + reading_heading("暂未完成", "阅览提示")
                                     + f"<div class='notice'>{html.escape(text)}</div><a class='button primary' href='/'>返回首页</a>" + footer()))

    def do_GET(self):
        parsed = urlsplit(self.path)
        path = parsed.path
        status = self.bridge.status() if path in ("/ask", "/health", "/inbox") else None
        if path == "/health":
            self.response(200, json.dumps({"ok": True, **status, "display": "server-rendered-html"}).encode(), "application/json")
            return
        csrf = self.session()
        if not csrf:
            body = (header() + "<section class='unlock'><span class='unlock-mark' aria-hidden='true'>m</span>"
                    "<h1>打开你的<br>科技资讯。</h1><p class='subtitle'>关注 AI 产业、产品与最新研究。</p>"
                    "<form class='unlock-form' method='post' action='/unlock'><label for='code'>8 位访问码</label>"
                    "<input id='code' name='code' type='password' inputmode='numeric' maxlength='8' autocomplete='off' required>"
                    "<button class='primary'>进入资讯</button></form><p class='section-note'>请使用首次连接时提供的访问码。</p></section>" + footer())
            self.response(200, document(body))
            return
        if path == "/ask":
            ident = uuid.uuid4().hex
            proof = hmac.new(csrf.encode(), ident.encode(), hashlib.sha256).hexdigest()
            notice_text = ("Muse 的连接暂不可用。已保存的消息仍可阅读，请稍后刷新连接状态。"
                           if status.get("cloud_rejected") else "正在连接 Muse。你可以先阅读已保存的消息。"
                           if status["paired"] else "请先在手机 Muse 中完成设备配对，再开始提问。")
            notice = f"<div class='notice'>{notice_text}</div>" if not status["connected"] else ""
            recent = "".join(f"<article class='item'><a href='/job/{r['id']}'>{html.escape(r['prompt'][:80])}</a><div class='status'>{state_label(r['state'])}</div></article>" for r in self.bridge.store.recent()) or "<p class='section-note'>还没有提问记录。写下第一个问题，回答会留在这里。</p>"
            body = (header(status, 'ask') + page_heading("问 Muse", "把一条资讯，读得更明白。") + notice
                    + "<form class='ask-form' method='post' action='/ask'>"
                    f"<input type='hidden' name='id' value='{ident}'><input type='hidden' name='proof' value='{proof}'>"
                    f"<textarea id='prompt' name='prompt' aria-label='你的问题' maxlength='{MAX_PROMPT}' required placeholder='写下你的问题…'></textarea>"
                    f"<div class='ask-actions'><button class='primary'{' disabled' if not status['connected'] else ''}>发送给 Muse</button></div></form>"
                    + section_heading("最近的问题") + f"<section class='archive'>{recent}</section>"
                    + "<nav class='utility-nav'><a class='text-link' href='/'>返回科技资讯</a><a class='text-link' href='/ask'>刷新连接状态</a></nav>" + footer())
            self.response(200, document(body, '问 Muse'))
            return
        if path in ('/', '/ai-news') or path.startswith('/ai-news/'):
            mode = parse_qs(parsed.query).get('mode', ['selected'])[0]
            if mode not in MODES:
                self.error_page('没有这个资讯栏目', 404)
                return
            topic = parse_qs(parsed.query).get('topic', ['selected'])[0]
            if topic not in NEWS_TOPICS:
                self.error_page('没有这个资讯分类', 404)
                return
            try:
                page = max(0, int(parse_qs(parsed.query).get('page', ['0'])[0]))
            except ValueError:
                page = 0
            if path in ('/', '/ai-news'):
                feed_status = self.bridge.feed.status(mode)
                all_articles = self.bridge.feed.items(mode, limit=100)
                category = NEWS_TOPICS[topic][1]
                if category:
                    all_articles = [row for row in all_articles if row.get('category') == category]
                count = max(1, (len(all_articles) + 9) // 10)
                page = min(page, count - 1)
                body = (header(active='news') + page_heading('科技资讯', '来自 AIHOT 的' + ('精选。' if mode == 'selected' else '全部资讯。'))
                        + topic_navigation(path, mode, topic)
                        + news_sync_note(feed_status))
                articles = all_articles[page * 10:(page + 1) * 10]
                if articles and page == 0:
                    body += news_feature(articles[0], mode, topic)
                    articles = articles[1:]
                body += '<section class="archive">' + ''.join(news_item(row, mode, topic) for row in articles) + '</section>'
                if all_articles:
                    body += pager(path + '?mode=' + mode + '&topic=' + topic, page, count)
                elif feed_status['last_success']:
                    body += empty_state('这个分类暂无资讯', '可以切换到精选，查看最近同步的内容。', '查看精选', '/')
                body += "<p class='section-note'>首页每分钟更新，打开摘要后暂停。</p>" + footer()
                self.response(200, document(body, 'Muse · 科技资讯', refresh=60 if page == 0 else None, page_class='news-home'))
                return
            match = re.fullmatch(r'/ai-news/([A-Za-z0-9_-]{1,96})(/text)?', path)
            row = self.bridge.feed.get(match.group(1), mode) if match else None
            if not row:
                self.error_page('这条资讯已不在当前列表中，请返回资讯栏目查看最新内容。', 404)
                return
            text = news_text(row)
            if match.group(2):
                self.response(200, text.encode(), 'text/plain; charset=utf-8')
                return
            reading_pages = pages(text)
            page = min(page, len(reading_pages) - 1)
            return_url = '/?mode=' + mode + '&topic=' + topic
            body = (header(active='news', compact=True, back_url=return_url) + reading_heading(row['title'], 'AIHOT · 资讯摘要')
                    + reading_progress(page, len(reading_pages)) + answer_html(reading_pages[page])
                    + pager(f"/ai-news/{row['id']}?mode={mode}&topic={topic}", page, len(reading_pages))
                    + news_provenance(row) + f"<nav class='utility-nav'><a class='text-link' href='{html.escape(return_url, quote=True)}'>返回资讯</a>"
                    + "<a class='text-link' href='/ask'>问 Muse</a></nav>" + footer())
            self.response(200, document(body, row['title'], page_class='reading'))
            return
        if path == "/inbox":
            messages = self.bridge.store.inbox()
            body = header(status, "inbox") + page_heading("收件箱", "每天 08:00，一份五分钟新闻。")
            if messages:
                body += message_cover(messages[0])
                if len(messages) > 1:
                    body += section_heading("过往来信") + "<section class='archive'>"
                    body += "".join(f"<article class='item'><a href='/message/{m['id']}'>{html.escape(m['title'])}</a><div class='meta'>{received_time(m['created'])}</div></article>" for m in messages[1:]) + "</section>"
            else:
                body += empty_state("来信还在路上", "Muse 发来的内容会保存在这里。先去问一个你感兴趣的问题。", "向 Muse 提问", "/ask")
            body += ("<p class='section-note'>每 60 秒自动更新。打开正文后暂停刷新，安心阅读。</p>"
                     "<nav class='utility-nav'><a class='text-link' href='/inbox'>立即刷新</a><a class='text-link' href='/ask'>返回提问</a></nav>" + footer())
            self.response(200, document(body, "Muse 收件箱", refresh=INBOX_REFRESH))
            return
        message_match = re.fullmatch(r"/message/([a-f0-9]{32})(/text)?", path)
        if message_match:
            message = self.bridge.store.message(message_match.group(1))
            if not message:
                self.error_page("没有找到这条消息", 404)
                return
            if message["withdrawal_reason"]:
                self.response(409, document(header(active="inbox") + reading_heading("这条消息已撤回", "阅览提示")
                                           + "<div class='notice'>" + html.escape(message["withdrawal_reason"]) + "</div><a class='button primary' href='/inbox'>返回收件箱</a>" + footer()))
                return
            if message_match.group(2):
                self.response(200, message["text"].encode(), "text/plain; charset=utf-8")
                return
            try:
                page = max(0, int(parse_qs(parsed.query).get("page", ["0"])[0]))
            except ValueError:
                page = 0
            message_pages = pages(message["text"])
            page = min(page, len(message_pages) - 1)
            label = "Muse 来信 / 试阅" if "-preview-" in message["delivery_id"] else "Muse 来信"
            body = (header(active="inbox", compact=True) + reading_heading(message["title"], label, message["created"])
                    + reading_progress(page, len(message_pages)) + answer_html(message_pages[page])
                    + pager(f"/message/{message['id']}", page, len(message_pages))
                    + "<nav class='utility-nav'><a class='text-link' href='/inbox'>返回收件箱</a><a class='text-link' href='/ask'>返回提问</a></nav>" + footer())
            self.response(200, document(body, message["title"], page_class="reading"))
            return
        match = re.fullmatch(r"/job/([a-f0-9]{32})(/text)?", path)
        job = self.bridge.store.get(match.group(1)) if match else None
        if not job:
            self.error_page("没有找到这个问题", 404)
            return
        if match.group(2):
            if job["state"] != "complete":
                self.error_page("还没有收到完整回答", 409)
                return
            self.response(200, job["answer"].encode(), "text/plain; charset=utf-8")
            return
        try:
            page = max(0, int(parse_qs(parsed.query).get("page", ["0"])[0]))
        except ValueError:
            page = 0
        answer_pages = pages(job["answer"])
        page = min(page, len(answer_pages) - 1)
        body = (header(active="ask", compact=True) + reading_heading(state_label(job["state"]), "你的提问")
                + f"<div class='question-context'><span class='meta'>你的问题</span>{html.escape(job['prompt'])}</div>")
        if job["state"] == "complete":
            body += reading_progress(page, len(answer_pages)) + answer_html(answer_pages[page]) + pager(f"/job/{job['id']}", page, len(answer_pages))
        elif job["state"] == "failed":
            body += f"<div class='notice'>{html.escape(job['reason'])}</div>"
        else:
            body += "<section class='waiting'><div class='waiting-number' aria-hidden='true'>…</div><h2>给思考一点时间。</h2><p>Muse 正在整理回答。稍后刷新，就可以继续阅读。</p>"
            body += f"<a class='button primary' href='/job/{job['id']}'>刷新回答</a></section>"
        body += "<nav class='utility-nav'><a class='text-link' href='/'>返回首页</a><a class='text-link' href='/ask'>再问一个问题</a></nav>" + footer()
        self.response(200, document(body, page_class="reading"))

    def do_POST(self):
        try:
            if self.headers.get("Transfer-Encoding") or not self.headers.get("Content-Type", "").startswith("application/x-www-form-urlencoded"):
                raise ValueError("请通过页面表单提交")
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= MAX_PACKET:
                raise ValueError("提交内容过长或为空")
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + self.headers.get("Host", ""):
                raise ValueError("提交来源不符合要求")
            values = parse_qs(self.rfile.read(size).decode("utf-8"), keep_blank_values=True, max_num_fields=8)
            one = lambda key: values.get(key, [""])[0]
            if self.path == "/unlock":
                token = self.bridge.store.login(one("code"), self.client_address[0])
                if not token:
                    self.error_page("访问码不正确；多次输错后请等候 5 分钟", 403)
                    return
                self.redirect("/", [("Set-Cookie", f"km_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_AGE}")])
                return
            csrf, ident = self.session(), one("id")
            if not csrf or not JOB_ID.fullmatch(ident) or not hmac.compare_digest(one("proof"), hmac.new(csrf.encode(), ident.encode(), hashlib.sha256).hexdigest()):
                self.error_page("页面已失效，请重新打开首页", 403)
                return
            if self.path != "/ask":
                self.error_page("没有这个入口", 404)
                return
            if not self.bridge.status()["connected"]:
                self.error_page("Muse 当前未连接，请先完成配对", 409)
                return
            if self.bridge.store.submit(ident, one("prompt").strip(), one("excerpt")):
                threading.Thread(target=self.bridge.send, args=(ident,), daemon=True).start()
            self.redirect("/job/" + ident)
        except (ValueError, UnicodeError) as exc:
            self.error_page(str(exc))


def state_label(state):
    return {"sending": "正在发送", "waiting": "等待 Muse 回答", "complete": "Muse 的回答", "failed": "未完成"}[state]


class PublishHandler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(5)
        try:
            line = self.rfile.readline(MAX_PACKET + 1)
            if len(line) > MAX_PACKET:
                raise ValueError("packet too large")
            data = json.loads(line)
            if data.get("op") == "notify":
                response = self.server.store.notify(data.get("delivery_id"), data.get("title"), data.get("text"))
            elif data.get("op", "reply") == "reply":
                response = self.server.store.publish(data.get("job_id"), data.get("text"))
            elif data.get("op") == "news_source":
                response = self.server.store.check_news_source(data.get("url"))
            else:
                raise ValueError("unsupported operation")
        except (OSError, ValueError, TypeError, AttributeError, LookupError) as exc:
            response = {"ok": False, "error": str(exc)[:500] or "invalid request"}
        self.wfile.write(json.dumps(response).encode() + b"\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--state-dir", default="state")
    parser.add_argument("--sdk-socket", default="/run/musegadget/musegadget.sock")
    parser.add_argument("--publish-socket", help="Local reply socket; defaults to STATE_DIR/publish.sock")
    args = parser.parse_args()
    os.umask(0o077)
    store = Store(args.state_dir)
    store.recover()
    path = Path(args.publish_socket) if args.publish_socket else store.directory / "publish.sock"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_socket():
            parser.error("publish socket path already contains a non-socket file")
        path.unlink()  # Only this application's Unix socket, never device data.
    publish = socketserver.ThreadingUnixStreamServer(str(path), PublishHandler)
    publish.daemon_threads = True
    publish.store = store
    threading.Thread(target=publish.serve_forever, daemon=True).start()
    Handler.bridge = Bridge(store, args.sdk_socket)
    Handler.bridge.feed.start()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Kindle reader listening on {args.host}:{args.port}; Muse connection status is checked live", flush=True)
    try:
        server.serve_forever()
    finally:
        Handler.bridge.feed.stop.set()
        publish.shutdown()
        publish.server_close()


if __name__ == "__main__":
    main()
