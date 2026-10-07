"""Offline layout preview using original examples, never a simulated Muse reply."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aihot_feed import FeedCache
from bridge import Bridge, Handler, Store, ThreadingHTTPServer

EXAMPLES = [
    ('industry', '从模型到产品，科技的下一步在哪里', '这是一篇原创布局示例，不是真实新闻。\n行业变化值得慢慢观察：新工具怎样进入日常工作，技术又怎样变成可靠的产品？'),
    ('ai-products', '把复杂留给主机，把阅读留给墨水屏', '原创示例：黑白、大字号和清晰的分页，让一条资讯可以安静地读完。'),
    ('ai-models', '小模型与本地运行：一个示例话题', '原创示例：选型需要同时考虑任务、资源和验证，而不是只比较参数数量。'),
    ('paper', '一篇研究，先看问题，再看证据', '原创示例：先读研究问题、实验设计与边界，再判断结论能用于什么场景。'),
    ('tip', '从一条科技资讯开始今天的阅读', '原创示例：保留出处，把摘要当作阅读入口，重要信息再回到原文核对。'),
]


class DemoHandler(Handler):
    def response(self, code, body=b'', content_type='text/html; charset=utf-8', extra=()):
        if content_type.startswith('text/html'):
            body = body.replace('来自 AIHOT 的精选。'.encode(), '原创内容，用于界面预览。'.encode())
            body = body.replace('更新于 '.encode(), '示例生成于 '.encode())
            body = body.replace(b"<main id='content'>", b"<main id='content'>" +
                                "<p class='notice'>演示 · 原创示例内容，非实时新闻</p>".encode())
        super().response(code, body, content_type, extra)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--state-dir', default='state/demo')
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).isoformat()
    items = [{'id': 'demo-' + str(i), 'title': title, 'summary': summary,
              'reason': '原创界面示例，不代表 AIHOT 的实际收录或推荐。',
              'category': category, 'source': {'name': '原创示例'},
              'publishedAt': stamp, 'discoveredAt': stamp,
              'links': {'aihot': 'https://aihot.news/', 'original': 'https://example.com/'}}
             for i, (category, title, summary) in enumerate(EXAMPLES)]
    def fetch(url, headers):
        return 200, {'Cache-Control': 's-maxage=3600'}, json.dumps({'items': items}).encode()
    store = Store(args.state_dir)
    feed = FeedCache(args.state_dir, fetcher=fetch)
    for mode in ('selected', 'all'):
        feed.sync(mode)
    DemoHandler.bridge = Bridge(store, str(store.directory / 'absent-sdk.sock'), feed)
    print(f'Offline demo: http://127.0.0.1:{args.port}/; access code: {store.directory}/access_code', flush=True)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), DemoHandler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
