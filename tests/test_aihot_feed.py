import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aihot_feed import FeedCache
from bridge import Bridge, Handler, Store, ThreadingHTTPServer


def item(ident='news-one', title='一条 AI 资讯'):
    return {'id': ident, 'title': title, 'summary': '完整摘要\n第二段', 'reason': '站点推荐理由',
            'source': {'name': '发布机构'}, 'category': 'industry', 'publishedAt': '2026-10-06T00:00:00Z',
            'discoveredAt': '2026-10-07T00:00:00Z',
            'links': {'aihot': 'https://aihot.news/items/' + ident,
                      'original': 'https://example.com/news/' + ident}}


class FeedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = 1791331200.0
        self.calls = []
        self.responses = []
        def fetch(url, headers):
            self.calls.append((url, headers))
            return self.responses.pop(0)
        self.feed = FeedCache(self.tmp.name, fetcher=fetch, clock=lambda: self.now)

    def tearDown(self):
        self.tmp.cleanup()

    def response(self, items, etag='v1', status=200, **headers):
        return status, {'ETag': etag, 'Cache-Control': 'public, s-maxage=60', **headers}, json.dumps({'items': items}).encode()

    def test_conditional_refresh_keeps_content_on_304_and_honors_cache_ttl(self):
        self.responses = [self.response([item()]), (304, {'Cache-Control': 'public, s-maxage=120'}, b'')]
        self.feed.sync('selected')
        first = self.feed.get('news-one', 'selected')
        self.now += 60
        self.feed.sync('selected')
        self.assertEqual(self.calls[1][1]['If-None-Match'], 'v1')
        self.assertEqual(self.feed.get('news-one', 'selected'), first)
        self.assertEqual(self.feed.status('selected')['next_check'], self.now + 120)
        self.assertEqual(self.feed.status('selected')['count'], 1)

    def test_corrections_and_removed_selections_replace_the_visible_snapshot(self):
        self.responses = [self.response([item(), item('news-two')]), self.response([item('news-two', '修订标题')], 'v2')]
        self.feed.sync('selected')
        self.now += 60
        self.feed.sync('selected')
        self.assertIsNone(self.feed.get('news-one', 'selected'))
        self.assertEqual(self.feed.get('news-two', 'selected')['title'], '修订标题')
        self.assertEqual(self.feed.status('selected')['count'], 1)

    def test_rate_limit_preserves_last_good_copy_and_obeys_retry_after(self):
        self.responses = [self.response([item()]), (429, {'Retry-After': '600'}, b'')]
        self.feed.sync('selected')
        self.now += 60
        self.feed.sync('selected')
        status = self.feed.status('selected')
        self.assertEqual(status['next_check'], self.now + 600)
        self.assertTrue(status['error'])
        self.assertIsNotNone(self.feed.get('news-one', 'selected'))
        self.assertEqual(status['last_success'], self.now - 60)

    def test_invalid_response_cannot_erase_good_content_or_poison_the_etag(self):
        self.responses = [self.response([item()]), (200, {'ETag': 'bad'}, b'{bad-json')]
        self.feed.sync('selected')
        self.now += 60
        self.feed.sync('selected')
        self.assertEqual(self.feed.status('selected')['etag'], 'v1')
        self.assertEqual(self.feed.status('selected')['count'], 1)
        self.assertTrue(self.feed.status('selected')['error'])

    def test_modes_and_persisted_content_are_independent(self):
        self.responses = [self.response([item()], 'selected-v1'), self.response([item('all-only')], 'all-v1')]
        self.feed.sync('selected')
        self.feed.sync('all')
        restarted = FeedCache(self.tmp.name)
        self.assertIsNotNone(restarted.get('news-one', 'selected'))
        self.assertIsNone(restarted.get('all-only', 'selected'))
        self.assertIsNotNone(restarted.get('all-only', 'all'))
        self.assertEqual(restarted.status('all')['etag'], 'all-v1')

    def test_unsafe_links_and_missing_source_dates_are_handled_truthfully(self):
        bad = item()
        bad['links']['original'] = 'javascript:alert(1)'
        bad['publishedAt'] = None
        self.responses = [self.response([bad])]
        self.feed.sync('selected')
        saved = self.feed.get('news-one', 'selected')
        self.assertEqual(saved['original_url'], '')
        self.assertIsNone(saved['published_at'])
        self.assertTrue(saved['discovered_at'])

    def test_category_upgrade_invalidates_only_old_feed_etags_and_retains_cache(self):
        self.responses = [self.response([item()])]
        self.feed.sync('selected')
        self.assertEqual(self.feed.get('news-one')['category'], 'industry')
        with self.feed.db() as db:
            db.execute('PRAGMA user_version=0')
        upgraded = FeedCache(self.tmp.name)
        self.assertEqual(upgraded.status()['etag'], '')
        self.assertEqual(upgraded.status()['next_check'], 0)
        self.assertIsNotNone(upgraded.get('news-one'))


class FeedHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        feed = FeedCache(self.tmp.name, fetcher=lambda *_: (200, {'ETag': 'v1'}, json.dumps({'items': [item(title='<script>unsafe</script>')] }).encode()))
        feed.sync('selected')
        self.feed = feed
        bridge = Bridge(self.store, Path(self.tmp.name) / 'absent.sock', feed=feed)
        class TestHandler(Handler):
            pass
        TestHandler.bridge = bridge
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), TestHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.cookie = 'km_session=' + self.store.login(self.store.code, 'test')

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def request(self, path, cookie=True):
        client = http.client.HTTPConnection(*self.server.server_address)
        client.request('GET', path, headers={'Cookie': self.cookie} if cookie else {})
        response = client.getresponse()
        result = response.status, response.read().decode()
        client.close()
        return result

    def test_feed_is_private_safe_and_list_refresh_does_not_interrupt_reading(self):
        _, anonymous = self.request('/ai-news', cookie=False)
        self.assertIn('访问码', anonymous)
        self.assertNotIn('unsafe', anonymous)
        code, listing = self.request('/ai-news')
        self.assertEqual(code, 200)
        self.assertIn("http-equiv='refresh' content='60'", listing)
        self.assertIn('&lt;script&gt;', listing)
        self.assertNotIn('<script>', listing)
        code, reading = self.request('/ai-news/news-one')
        self.assertEqual(code, 200)
        self.assertNotIn("http-equiv='refresh'", reading)
        self.assertIn('原文发布时间', reading)
        self.assertIn('站点收录时间', reading)
        self.assertIn('https://aihot.news/items/news-one', reading)
        self.assertIn('https://example.com/news/news-one', reading)

    def test_reading_text_preserves_summary_and_pagination_keeps_mode(self):
        code, text = self.request('/ai-news/news-one/text')
        self.assertEqual(code, 200)
        self.assertIn('完整摘要\n第二段', text)
        self.assertIn('站点推荐理由', text)
        from reader_ui import pager
        self.assertIn('/ai-news?mode=all&amp;page=1', pager('/ai-news?mode=all', 0, 2))
        code, _ = self.request('/ai-news/news-one?mode=all')
        self.assertEqual(code, 404)

    def test_home_is_news_and_does_not_show_inbox_or_question_history(self):
        self.store.notify('old-inbox', 'PRIVATE INBOX', '旧消息正文')
        self.store.submit('a' * 32, 'PRIVATE QUESTION', '')
        code, home = self.request('/')
        self.assertEqual(code, 200)
        self.assertIn('科技资讯', home)
        self.assertIn("http-equiv='refresh' content='60'", home)
        self.assertIn('/ai-news/news-one', home)
        self.assertNotIn('PRIVATE INBOX', home)
        self.assertNotIn('PRIVATE QUESTION', home)
        self.assertNotIn("href='/inbox'", home)
        self.assertNotIn("href='/#ask'", home)
        self.assertNotIn('<textarea', home)
        self.assertIn("href='/ask'", home)

    def test_topic_filter_is_source_based_and_ask_never_auto_refreshes(self):
        product = item('product-one', 'ONLY PRODUCT TITLE')
        product['category'] = 'ai-products'
        industry = item('industry-one', 'ONLY INDUSTRY TITLE')
        self.feed.fetcher = lambda *_: (200, {}, json.dumps({'items': [product, industry]}).encode())
        self.feed.sync('selected')
        code, filtered = self.request('/?topic=industry')
        self.assertEqual(code, 200)
        self.assertIn('ONLY INDUSTRY TITLE', filtered)
        self.assertNotIn('ONLY PRODUCT TITLE', filtered)
        _, reading = self.request('/ai-news/industry-one?topic=industry')
        self.assertIn("href='/?mode=selected&amp;topic=industry'", reading)
        self.assertEqual(self.request('/?topic=unknown')[0], 404)
        code, form = self.request('/ask')
        self.assertEqual(code, 200)
        self.assertNotIn("http-equiv='refresh'", form)
        self.assertEqual(form.count('<textarea'), 1)
        self.assertIn("name='proof'", form)


if __name__ == '__main__':
    unittest.main()
