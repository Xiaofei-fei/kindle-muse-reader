from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from news_sources import allowed_url, publication_date, source_urls


class NewsDateTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 7, 2, 0, tzinfo=timezone.utc).timestamp()
        self.url = "https://www.news.cn/20261007/article.html"

    def test_old_story_and_future_story_are_not_fresh(self):
        for date in ("2025-10-07T21:12:19+08:00", "2026-10-07T18:00:00+08:00"):
            page = f'<title>标题写着今天也无效</title><meta name="publishdate" content="{date}">'
            self.assertFalse(publication_date(page, self.url, self.now)["fresh"])
        valid = '<meta property="article:published_time" content="2026-10-07T09:00:00+08:00">'
        self.assertTrue(publication_date(valid, self.url, self.now)["fresh"])

    def test_modified_date_does_not_make_old_article_fresh(self):
        page = '<script type="application/ld+json">{"datePublished":"2025-10-07T10:00:00Z","dateModified":"2026-10-07T01:00:00Z"}</script>'
        self.assertFalse(publication_date(page, self.url, self.now)["fresh"])
        with self.assertRaises(ValueError):
            publication_date('<title>今天新闻</title>', self.url, self.now)

    def test_private_hosts_credentials_and_unapproved_publishers_are_rejected(self):
        for url in ("http://www.news.cn/article", "https://127.0.0.1/", "https://192.168.1.123/",
                    "https://www.news.cn.attacker.invalid/", "https://user:password@www.news.cn/", "https://www.news.cn:8443/"):
            with self.assertRaises(ValueError):
                allowed_url(url)
        self.assertEqual(allowed_url(self.url), self.url)
        self.assertEqual(source_urls('来源：https://www.news.cn/article.html）'), ['https://www.news.cn/article.html'])


if __name__ == "__main__":
    unittest.main()
