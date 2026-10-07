"""Verify publication dates from public news pages; never infer a fresh date."""
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import re
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

HOSTS = frozenset({
    "www.news.cn", "news.cn", "english.news.cn", "www.xinhuanet.com",
    "news.cctv.com", "www.people.com.cn", "politics.people.com.cn", "world.people.com.cn",
    "www.reuters.com", "reuters.com", "apnews.com", "www.apnews.com",
    "www.bbc.com", "bbc.com", "www.bbc.co.uk", "www.theguardian.com",
    "www.nytimes.com", "cn.nytimes.com", "www.ft.com", "www.france24.com",
    "openai.com", "www.anthropic.com", "anthropic.com", "ai.meta.com",
})
DATE_KEYS = frozenset({"article:published_time", "datepublished", "pubdate", "publishdate",
                       "date", "dc.date", "dcterms.date", "parsely-pub-date", "og:release_date"})


def allowed_url(url):
    if not isinstance(url, str) or len(url) > 2048:
        raise ValueError("invalid source URL")
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in HOSTS or parts.port not in (None, 443) or parts.username or parts.password:
        raise ValueError("Use an HTTPS article URL from an approved news publisher")
    return url


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        allowed_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class PageDates(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.dates, self.title, self.scripts = [], [], []
        self.in_title, self.in_json = False, False
        self.script = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            key = (attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or "").lower()
            if key in DATE_KEYS and attrs.get("content"):
                self.dates.append(attrs["content"])
        elif tag == "title":
            self.in_title = True
        elif tag == "script" and attrs.get("type") == "application/ld+json":
            self.in_json, self.script = True, []

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        elif tag == "script" and self.in_json:
            self.scripts.append("".join(self.script))
            self.in_json = False

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)
        if self.in_json:
            self.script.append(data)

    def published_dates(self):
        def visit(value):
            if isinstance(value, dict):
                if isinstance(value.get("datePublished"), str):
                    self.dates.append(value["datePublished"])
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        for script in self.scripts:
            try:
                visit(json.loads(script))
            except (ValueError, RecursionError):
                pass
        return self.dates


def publication_date(html, url, now):
    parser = PageDates()
    parser.feed(html)
    parsed = []
    for raw in parser.published_dates():
        try:
            value = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
            if value.tzinfo is None:
                host = urlsplit(url).hostname
                tz = ZoneInfo("Asia/Shanghai") if host and (host.endswith(".cn") or host.endswith(".com.cn")) else timezone.utc
                value = value.replace(tzinfo=tz)
            parsed.append(value)
        except (ValueError, OverflowError):
            pass
    if not parsed:
        raise ValueError("Article has no verifiable publication date; do not use it as today's news")
    # Prefer the oldest published date, so an update cannot turn an old story fresh.
    published = min(parsed)
    stamp = published.timestamp()
    return {"url": url, "title": "".join(parser.title).strip()[:250],
            "published_at": published.isoformat(), "published_date": published.date().isoformat(),
            "published_timestamp": stamp, "checked_timestamp": now,
            "fresh": now - 86400 <= stamp <= now}


def check_source(url, now=None):
    allowed_url(url)
    now = time.time() if now is None else now
    request = Request(url, headers={"User-Agent": "KindleMuseReader/1.0", "Accept": "text/html"})
    with build_opener(SafeRedirect()).open(request, timeout=8) as response:
        if response.headers.get_content_type() not in ("text/html", "application/xhtml+xml"):
            raise ValueError("Source is not an article page")
        body = response.read(512000)
        charset = response.headers.get_content_charset() or "utf-8"
        source = publication_date(body.decode(charset, errors="replace"), response.url, now)
    if source["fresh"]:
        source["verification"] = "Publisher metadata places publication within the past 24 hours"
    else:
        source["verification"] = "Publication is older than 24 hours or in the future; exclude this story"
    return source


def source_urls(text):
    return list(dict.fromkeys(u.rstrip("）)]}.,;，。") for u in re.findall(r"https?://[^\s<>]+", text)))
