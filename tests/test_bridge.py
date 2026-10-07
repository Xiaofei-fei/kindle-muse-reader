import http.client
import json
from pathlib import Path
import re
import sys
import tempfile
import threading
import unittest
from urllib.parse import urlencode
import uuid
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bridge import Bridge, Handler, Store, ThreadingHTTPServer, pages


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.ident = uuid.uuid4().hex

    def tearDown(self):
        self.tmp.cleanup()

    def test_ack_is_not_complete_and_callback_before_ack_wins(self):
        self.store.submit(self.ident, "真实问题", "摘录")
        self.store.sent(self.ident, True)
        self.assertEqual(self.store.get(self.ident)["state"], "waiting")
        self.store.publish(self.ident, "完整回答")
        self.store.sent(self.ident, False)
        self.assertEqual(self.store.get(self.ident)["state"], "complete")

    def test_submission_and_reply_replays_are_idempotent(self):
        self.assertTrue(self.store.submit(self.ident, "问题", ""))
        self.assertFalse(self.store.submit(self.ident, "问题", ""))
        with self.assertRaises(ValueError):
            self.store.submit(self.ident, "另一个问题", "")
        self.store.publish(self.ident, "完成")
        self.assertTrue(self.store.publish(self.ident, "完成")["duplicate"])
        with self.assertRaises(ValueError):
            self.store.publish(self.ident, "覆盖答案")

    def test_unknown_and_expired_replies_are_rejected(self):
        with self.assertRaises(ValueError):
            self.store.publish(self.ident, "孤立回答")
        self.store.submit(self.ident, "问题", "")
        with self.store.db() as db:
            db.execute("UPDATE jobs SET deadline=0")
        with self.assertRaises(ValueError):
            self.store.publish(self.ident, "迟到回答")
        self.assertEqual(self.store.get(self.ident)["state"], "failed")

    def test_restart_does_not_resend_ambiguous_requests(self):
        self.store.submit(self.ident, "问题", "")
        self.store.recover()
        self.assertEqual(self.store.get(self.ident)["state"], "failed")

    def test_invalid_input_and_login_limits(self):
        with self.assertRaises(ValueError):
            self.store.submit(self.ident, "", "")
        with self.assertRaises(ValueError):
            self.store.submit(self.ident, "问题", "摘" * 10001)
        for _ in range(5):
            self.assertIsNone(self.store.login("invalid", "client"))
        self.assertIsNone(self.store.login(self.store.code, "client"))
        token = self.store.login(self.store.code, "other-client")
        self.assertIsNotNone(self.store.session(token))
        self.assertIsNone(self.store.session("invalid"))

    def test_pagination_preserves_every_character(self):
        text = ("中文段落🙂\n" * 1200) + "结尾"
        result = pages(text)
        self.assertEqual("".join(result), text)
        self.assertTrue(all(len(p) <= 1000 for p in result))

    def test_inbox_is_independent_idempotent_and_survives_restart(self):
        message = self.store.notify("reader-message-2026-10-07", "阅读消息", "完整正文")
        replay = self.store.notify("reader-message-2026-10-07", "阅读消息", "完整正文")
        self.assertTrue(replay["duplicate"])
        self.assertEqual(message["message_id"], replay["message_id"])
        with self.assertRaises(ValueError):
            self.store.notify("reader-message-2026-10-07", "阅读消息", "改写后的正文")
        self.assertEqual(len(self.store.recent()), 0)
        restarted = Store(self.tmp.name)
        restarted.recover()
        self.assertEqual(restarted.message(message["message_id"])["text"], "完整正文")
        self.assertEqual(len(restarted.inbox()), 1)

    def test_inbox_rejects_invalid_content_and_limits_new_deliveries(self):
        for key, title, text in (("../path", "标题", "正文"), ("valid", " ", "正文"),
                                 ("valid", "题" * 161, "正文"), ("valid", "标题", "文" * 60001)):
            with self.assertRaises(ValueError):
                self.store.notify(key, title, text)
        for n in range(30):
            self.store.notify(f"delivery-{n}", "标题", "正文")
        self.assertTrue(self.store.notify("delivery-0", "标题", "正文")["duplicate"])
        with self.assertRaises(ValueError):
            self.store.notify("delivery-31", "标题", "正文")

    def test_news_requires_recent_verification_for_every_source(self):
        url = "https://www.news.cn/article.html"
        now = time.time()
        metadata = {"fresh": True, "checked_timestamp": now, "published_timestamp": now - 3600}
        with self.assertRaises(ValueError):
            self.store.notify("kindle-news-2026-10-07", "新闻", "新闻事实 " + url)
        with self.store.db() as db:
            db.execute("INSERT INTO news_sources VALUES (?,?)", (url, json.dumps(metadata)))
        with self.assertRaises(ValueError):
            self.store.notify("kindle-news-2026-10-07", "新闻", "新闻事实 " + url + " https://apnews.com/unverified")
        with self.store.db() as db:
            metadata["published_timestamp"] = now - 365 * 86400
            db.execute("UPDATE news_sources SET metadata=?", (json.dumps(metadata),))
        with self.assertRaises(ValueError):
            self.store.notify("kindle-news-2026-10-07", "新闻", "新闻事实 " + url)
        with self.store.db() as db:
            metadata["published_timestamp"] = now - 3600
            db.execute("UPDATE news_sources SET metadata=?", (json.dumps(metadata),))
        self.assertTrue(self.store.notify("kindle-news-2026-10-07", "新闻", "新闻事实 " + url)["ok"])


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.bridge = Bridge(self.store, Path(self.tmp.name) / "absent.sock")
        class TestHandler(Handler):
            bridge = self.bridge
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def request(self, method, path, data=None, cookie=None):
        client = http.client.HTTPConnection(*self.server.server_address)
        headers = {}
        body = urlencode(data) if data else None
        if data:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        if cookie:
            headers["Cookie"] = cookie
        client.request(method, path, body, headers)
        response = client.getresponse()
        result = (response.status, dict(response.getheaders()), response.read().decode())
        client.close()
        return result

    def login(self):
        status, headers, _ = self.request("POST", "/unlock", {"code": self.store.code})
        self.assertEqual(status, 303)
        return headers["Set-Cookie"].split(";")[0]

    def test_no_prompt_leak_before_login_and_no_js(self):
        self.store.submit(uuid.uuid4().hex, "PRIVATE QUESTION", "PRIVATE EXCERPT")
        status, _, text = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertNotIn("PRIVATE", text)
        self.assertNotIn("<script", text)
        self.assertIn("访问码", text)
        status, _, text = self.request("GET", "/health")
        self.assertFalse(json.loads(text)["connected"])

    def test_disconnected_and_forged_submissions_are_rejected(self):
        cookie = self.login()
        status, _, text = self.request("GET", "/ask", cookie=cookie)
        self.assertIn(" disabled", text)
        ident = re.search("name='id' value='([^']+)'", text).group(1)
        proof = re.search("name='proof' value='([^']+)'", text).group(1)
        self.assertEqual(self.request("POST", "/ask", {"id": ident, "proof": "forged", "prompt": "问题"}, cookie)[0], 403)
        self.assertEqual(self.request("POST", "/ask", {"id": ident, "proof": proof, "prompt": "问题"}, cookie)[0], 409)
        self.assertEqual(len(self.store.recent()), 0)

    def test_answer_is_escaped_and_paginates(self):
        ident = uuid.uuid4().hex
        self.store.submit(ident, "<script>prompt</script>", "")
        self.store.publish(ident, "<script>alert(1)</script>" + "测试" * 1600)
        cookie = self.login()
        status, _, text = self.request("GET", "/job/" + ident, cookie=cookie)
        self.assertEqual(status, 200)
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;script&gt;", text)
        self.assertIn("下一页", text)
        raw = self.request("GET", "/job/" + ident + "/text", cookie=cookie)[2]
        self.assertEqual(raw, self.store.get(ident)["answer"])

    def test_cross_origin_login_is_rejected(self):
        client = http.client.HTTPConnection(*self.server.server_address)
        client.request("POST", "/unlock", urlencode({"code": self.store.code}),
                       {"Content-Type": "application/x-www-form-urlencoded", "Origin": "http://untrusted.invalid"})
        response = client.getresponse()
        self.assertEqual(response.status, 400)
        self.assertEqual(response.getheader("Referrer-Policy"), "same-origin")
        response.read()
        client.close()

    def test_inbox_is_private_and_auto_refresh_does_not_interrupt_reading(self):
        message = self.store.notify("private", "PRIVATE TITLE <script>", "PRIVATE BODY <script>" + "中文" * 1300)
        for path in ("/inbox", "/message/" + message["message_id"], "/message/" + message["message_id"] + "/text"):
            self.assertNotIn("PRIVATE", self.request("GET", path)[2])
        cookie = self.login()
        inbox = self.request("GET", "/inbox", cookie=cookie)[2]
        self.assertIn("http-equiv='refresh' content='60'", inbox)
        self.assertIn("PRIVATE TITLE &lt;script&gt;", inbox)
        self.assertNotIn("<script>", inbox)
        page = self.request("GET", "/message/" + message["message_id"], cookie=cookie)[2]
        self.assertNotIn("http-equiv='refresh'", page)
        self.assertIn("下一页", page)
        self.assertNotIn("<script>", page)
        raw = self.request("GET", "/message/" + message["message_id"] + "/text", cookie=cookie)[2]
        self.assertEqual(raw, self.store.message(message["message_id"])["text"])

    def test_withdrawn_message_keeps_audit_but_cannot_be_read_or_replayed(self):
        message = self.store.notify("withdrawn-preview", "标题", "INCORRECT PREVIEW")
        self.store.withdraw(message["message_id"], "来源日期未通过核验")
        self.assertEqual(self.store.message(message["message_id"])["text"], "INCORRECT PREVIEW")
        self.assertEqual(self.store.inbox(), [])
        with self.assertRaises(ValueError):
            self.store.notify("withdrawn-preview", "标题", "INCORRECT PREVIEW")
        cookie = self.login()
        for path in ("/inbox", "/message/" + message["message_id"], "/message/" + message["message_id"] + "/text"):
            self.assertNotIn("INCORRECT PREVIEW", self.request("GET", path, cookie=cookie)[2])


if __name__ == "__main__":
    unittest.main()
