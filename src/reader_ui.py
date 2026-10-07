"""Static, monochrome reading UI for the Kindle's built-in browser."""
from datetime import datetime
import html
import math
import re
from zoneinfo import ZoneInfo

NEWS_TOPICS = {'selected': ('精选', ''), 'industry': ('产业', 'industry'),
               'products': ('产品', 'ai-products'), 'models': ('模型', 'ai-models'),
               'research': ('研究', 'paper'), 'practice': ('实践', 'tip')}
CATEGORY_LABELS = {value[1]: value[0] for value in NEWS_TOPICS.values() if value[1]}


CSS = """
*{box-sizing:border-box}
html{background:#fff;color:#000}
body{margin:0;font:20px Arial,'PingFang SC','Microsoft YaHei',sans-serif;line-height:1.6}
main{max-width:800px;margin:0 auto;padding:28px 32px 40px}
a{color:#000;text-decoration:none}a:focus,button:focus,input:focus,textarea:focus{outline:3px solid #000;outline-offset:4px}
button,a.button,input,textarea{-webkit-appearance:none}
.skip-link{position:absolute;left:-10000px;top:8px;padding:12px;background:#000;color:#fff;z-index:2}.skip-link:focus{left:8px}
.masthead{border-bottom:2px solid #000;padding-bottom:20px;margin-bottom:28px}
.brand-row{display:table;width:100%;margin-bottom:16px}.brand,.connection{display:table-cell;vertical-align:middle}
.brand{width:70%}.brand-name{font:56px Georgia,'Times New Roman',serif;letter-spacing:-3px;line-height:1;display:inline-block}
.brand-caption{font-size:16px;margin-left:18px;display:inline-block;vertical-align:middle;letter-spacing:2px}
.connection{text-align:right;font-size:16px;white-space:nowrap}.connection-dot{display:inline-block;width:8px;height:8px;border:1px solid #000;border-radius:50%;margin-right:8px}.is-online .connection-dot{background:#000}
.top-nav a{display:inline-block;padding:8px 20px 8px 0;margin-right:22px;font-size:19px;min-height:48px;border-bottom:2px solid transparent}
.top-nav a[aria-current='page']{border-bottom-color:#000;font-weight:bold}.top-nav a:last-child{margin-right:0}
h1,h2,h3,p{margin:0}h1,h2,h3{font-family:'Songti SC','STSong','Noto Serif CJK SC','SimSun',Georgia,serif}
h1{font-size:42px;line-height:1.3;font-weight:600}h2{font-size:30px;line-height:1.45;font-weight:600}h3{font-size:24px;line-height:1.5}
.page-heading{position:relative;padding:8px 112px 28px 0;min-height:118px}.page-heading .subtitle{font-size:18px;margin-top:10px;color:#555}
.date-mark{position:absolute;right:0;top:5px;text-align:right}.date-number{font:40px Georgia,'Times New Roman',serif;letter-spacing:-1px;line-height:1.2}.date-week{font-size:15px;margin-top:5px;color:#555}
.section-heading{margin:34px 0 18px;padding-top:22px;border-top:1px solid #b8b8b8}.section-heading h2{font-size:28px}.section-heading p{font-size:18px;color:#555;margin-top:8px}
.cover{border:1px solid #000;border-left:8px solid #000;padding:25px 26px 22px;margin-bottom:22px;border-radius:0 14px 14px 0}
.cover-top{font-size:17px;margin-bottom:19px}.cover-kind{font-weight:bold}.cover-time{float:right;color:#555}.cover-top:after{display:block;clear:both;content:''}
.cover h2{font-size:34px;line-height:1.45;letter-spacing:.4px;margin:0 0 14px;word-wrap:break-word}
.cover-topics{font-size:19px;color:#555;margin-bottom:6px}.reading-time{display:inline-block;font-size:17px;margin-left:18px}.cover-details{font-size:17px;color:#555;margin:10px 0 20px}
.cover-preview{font:23px 'Songti SC','STSong','SimSun',Georgia,serif;line-height:1.8;margin:12px 0 20px;white-space:pre-wrap;word-wrap:break-word}
.cover .button{margin:0}.cover-footer{margin-top:24px}
button,.button{display:inline-block;font:21px Arial,'PingFang SC','Microsoft YaHei',sans-serif;line-height:1.35;min-height:54px;padding:14px 22px;border:1px solid #000;background:#fff;color:#000;border-radius:7px;text-align:center;cursor:pointer}
.primary{color:#fff;background:#000;border:2px solid #000}.button:hover,button:hover{background:#f3f3f3;color:#000}.primary:hover{background:#000;color:#fff;text-decoration:underline}
.button:active,button:active{outline:2px solid #000;outline-offset:2px}button:disabled,.button.disabled{background:#f3f3f3;color:#555;border-color:#b8b8b8;cursor:default}
.text-link{display:inline-block;font-size:19px;padding:12px 0;min-height:48px;text-decoration:underline;text-underline-offset:5px}
.section-note,.meta{font-size:17px;color:#555}.section-note{margin:14px 0 24px}.empty{padding:28px 0 32px}.empty h2{margin-bottom:10px}.empty p{font-size:20px;color:#555;max-width:28em}.empty .button{margin-top:24px}
.section-heading#ask{margin-top:40px;padding-top:8px;border:0}.section-heading#ask h2{font-size:34px}
.ask-form{padding:0;margin:0 0 38px;background:#fff}.ask-form textarea{height:190px;margin:0;font-size:24px;line-height:1.7;padding:18px;border-radius:4px}
label{display:block;font-size:20px;font-weight:bold;margin:0 0 10px}
textarea,input{width:100%;font:22px Arial,'PingFang SC','Microsoft YaHei',sans-serif;line-height:1.55;color:#000;background:#fff;border:1px solid #000;border-radius:6px;padding:14px}
textarea{height:124px;resize:vertical}textarea::placeholder{color:#666}
.ask-actions{text-align:right;margin-top:16px}.ask-form .primary{min-width:160px;padding:14px 28px;border-radius:4px}
.item{padding:20px 0;border-bottom:1px solid #b8b8b8}.item a{display:block;font-size:23px;line-height:1.6;word-wrap:break-word}.item .meta,.item .status{font-size:17px;color:#555;margin-top:8px}
.archive{margin-bottom:24px}.notice{border-left:5px solid #000;background:#f3f3f3;padding:18px 22px;margin-bottom:24px;font-size:20px}
.utility-nav{border-top:1px solid #b8b8b8;margin-top:30px;padding-top:12px}.utility-nav a{margin-right:25px}
.page-footer{border-top:2px solid #000;padding-top:16px;margin-top:38px;font-size:15px;color:#555}.footer-brand{font:24px Georgia,'Times New Roman',serif;letter-spacing:-1px;color:#000;margin-right:14px}
.reading .masthead{margin-bottom:20px;padding-bottom:14px}.reading .brand-name{font-size:40px;letter-spacing:-2px}.reading .brand-caption{font-size:15px}.reading .brand-row{margin-bottom:0}.reading-back{display:table-cell;text-align:right;vertical-align:middle;white-space:nowrap}.reading-back a{font-size:17px;padding:12px 0;display:inline-block;min-height:48px;text-decoration:underline;text-underline-offset:5px}
.reading-heading{margin-bottom:18px}.reading-label{font-size:17px;margin-bottom:8px;color:#555}.reading-heading h1{font-size:34px;line-height:1.45;word-wrap:break-word}.reading-heading .meta{margin-top:12px}
.reading-meta{font-size:17px;color:#555;margin:16px 0 6px}.reading-progress{width:100%;height:3px;border:0;background:#f3f3f3;color:#000;-webkit-appearance:none;appearance:none;display:block;margin:0 0 27px}.reading-progress::-webkit-progress-bar{background:#f3f3f3}.reading-progress::-webkit-progress-value{background:#000}.reading-progress::-moz-progress-bar{background:#000}
.answer{font:26px 'Songti SC','STSong','Noto Serif CJK SC','SimSun',Georgia,serif;line-height:1.85;white-space:normal;overflow-wrap:break-word;word-wrap:break-word}
.text-line{display:block;white-space:pre-wrap}.text-blank{height:18px;line-height:18px}
.text-section{display:inline-block;font:bold 20px Arial,'PingFang SC',sans-serif;line-height:1.6;background:#f3f3f3;padding:5px 10px}
.text-heading{font-size:28px;font-weight:bold;line-height:1.7}.text-source,.text-intro{font:18px Arial,'PingFang SC',sans-serif;line-height:1.8;color:#555}
.question-context{border-left:3px solid #000;padding:9px 18px;background:#f3f3f3;margin-bottom:26px;font-size:22px;white-space:pre-wrap;word-wrap:break-word}.question-context .meta{display:block;margin-bottom:7px}
.pager{display:table;width:100%;border-top:2px solid #000;margin-top:32px;padding-top:20px}.pager-side,.pager-count{display:table-cell;vertical-align:middle}.pager-side{width:37%}.pager-side:last-child{text-align:right}.pager-side .button{width:100%}.pager-count{text-align:center;font-size:17px;color:#555}
.waiting{padding:30px 0}.waiting-number{font:70px Georgia,serif;line-height:1;margin-bottom:20px}.waiting h2{margin-bottom:16px}.waiting p{font-size:22px;line-height:1.8;margin-bottom:24px}
.unlock{padding:18px 0 0}.unlock-mark{display:inline-block;font:70px Georgia,serif;line-height:1;border-left:6px solid #000;padding:8px 18px;margin-bottom:26px}.unlock h1{font-size:38px;line-height:1.5}.unlock .subtitle{font-size:20px;color:#555;margin:16px 0 30px}.unlock-form{max-width:470px;background:#f3f3f3;padding:26px;border:1px solid #b8b8b8;border-radius:12px}.unlock input{letter-spacing:8px;margin-bottom:20px}.unlock button{width:100%}
.news-home .masthead{padding-bottom:18px;margin-bottom:18px}.news-home .brand-row{margin-bottom:0}.news-home .brand-name{font-size:46px}.news-home .brand-caption{letter-spacing:0;font-size:17px}
.news-home .page-heading{min-height:86px;padding-bottom:18px}.news-home .page-heading h1{font-size:32px}.news-home .page-heading .subtitle{font-size:16px;margin-top:5px}.news-home .date-number{font-size:32px}
.topic-nav{border-bottom:1px solid #000;margin-bottom:12px;white-space:normal}.topic-nav a{display:inline-block;font-size:18px;line-height:1.5;padding:12px 6px;min-height:52px;border-bottom:3px solid transparent}.topic-nav a[aria-current='page']{border-bottom-color:#000;font-weight:bold}
.news-home .sync-line{font-size:15px;color:#555;margin:0 0 26px;word-wrap:break-word}.sync-line a{text-decoration:underline}
.news-lead{padding:0 0 28px;border-bottom:2px solid #000}.news-category{font-size:16px;color:#555;margin-bottom:10px}.news-lead h2{font-size:33px;line-height:1.5;margin-bottom:14px;word-wrap:break-word}.news-lead .news-summary{font:22px 'Songti SC','STSong','SimSun',Georgia,serif;line-height:1.8;margin-bottom:14px;word-wrap:break-word}.news-lead .meta{font-size:15px;margin-bottom:15px}.news-lead .button{font-size:19px;padding:12px 20px;border-radius:2px}
.news-home .archive{margin:0 0 22px}.news-home .item{padding:23px 0}.news-home .item a{font:25px 'Songti SC','STSong','SimSun',Georgia,serif;line-height:1.6}.news-home .item .meta{font-size:15px;line-height:1.7}.news-home .pager{border-top:0;margin-top:0;padding-top:0}.news-home .page-footer{margin-top:28px;font-size:14px}
@media (max-width:600px){main{padding:22px 23px 32px}.brand-name{font-size:48px}.brand-caption{font-size:15px;margin-left:12px;letter-spacing:1px}.masthead{padding-bottom:14px;margin-bottom:22px}.cover{padding:20px 22px 22px}.cover h2{font-size:30px}.page-heading{padding-bottom:22px}.reading-heading h1{font-size:31px}}
@media (max-width:390px){main{padding:18px 17px 28px}.brand-name{font-size:44px}.brand-caption{display:block;font-size:14px;margin:7px 0 0}.brand{width:65%}.top-nav a{font-size:18px;margin-right:17px;padding-right:10px}.connection{font-size:15px}.page-heading{padding-right:83px;min-height:110px}h1{font-size:34px}.date-number{font-size:32px}.date-week{font-size:13px}.cover{padding:18px}.cover h2{font-size:27px}.cover-time{float:none;display:block;margin-top:5px}.button,button{font-size:20px;padding:14px 18px}.ask-form textarea{font-size:23px;padding:16px}.answer{font-size:24px}.text-heading{font-size:26px}.reading-heading h1{font-size:28px}.reading .brand-caption{display:inline-block;margin-left:12px}.pager-side{width:38%}.pager-count{font-size:15px}.pager .button{padding:14px 8px}}
@media (max-width:390px){.news-home .brand-caption{display:inline-block;font-size:15px;margin:0 0 0 10px}.news-home .brand{width:75%}.news-home .brand-name{font-size:39px}.news-home .reading-back a{font-size:16px}.news-home .page-heading{min-height:86px}.news-lead h2{font-size:29px}.news-lead .news-summary{font-size:21px}.news-home .item a{font-size:23px}.topic-nav a{font-size:17px;padding:12px 6px}}
"""


def document(body, title="Muse · 科技资讯", refresh=None, page_class=""):
    refresh_tag = f"<meta http-equiv='refresh' content='{refresh}'>" if refresh else ""
    return ("<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"{refresh_tag}<title>{html.escape(title)}</title><style>{CSS}</style></head>"
            f"<body class='{html.escape(page_class, quote=True)}'><a class='skip-link' href='#content'>跳到内容</a>"
            f"<main id='content'>{body}</main></body></html>").encode()


def local_date(timestamp=None):
    return datetime.fromtimestamp(timestamp, ZoneInfo("Asia/Shanghai")) if timestamp is not None else datetime.now(ZoneInfo("Asia/Shanghai"))


def received_time(timestamp):
    return local_date(timestamp).strftime("%Y-%m-%d %H:%M")


def header(status=None, active="news", compact=False, back_url=None):
    connection = ""
    if status is not None:
        label = ("已连接" if status["connected"] else "连接暂不可用" if status.get("cloud_rejected")
                 else "正在连接" if status["paired"] else "待配对")
        connection = (f"<div class='connection{' is-online' if status['connected'] else ''}'>"
                      f"<span class='connection-dot' aria-hidden='true'></span>{label}</div>")
    if compact:
        url, label = (("/ask", "继续提问") if active == "ask" else ("/", "科技资讯"))
        url = back_url or url
        connection = f"<div class='reading-back'><a href='{html.escape(url, quote=True)}'>{label}</a></div>"
    elif active == 'news':
        connection = "<div class='reading-back'><a href='/ask'>问 Muse</a></div>"
    links = []
    for key, url, label in (("news", "/", "资讯"), ("ask", "/ask", "问 Muse")):
        current = " aria-current='page'" if key == active else ""
        links.append(f"<a href='{url}'{current}>{label}</a>")
    nav = "" if compact or active == 'news' else f"<nav class='top-nav' aria-label='主要导航'>{''.join(links)}</nav>"
    return ("<header class='masthead'><div class='brand-row'><a class='brand' href='/' aria-label='Muse 科技首页'>"
            f"<span class='brand-name'>muse</span><span class='brand-caption'>科技资讯</span></a>{connection}</div>"
            f"{nav}</header>")


def footer():
    return "<footer class='page-footer'><span class='footer-brand'>muse</span>关注科技，每天读一点。</footer>"


def page_heading(title, subtitle):
    today = local_date()
    week = "一二三四五六日"[today.weekday()]
    return (f"<div class='page-heading'><h1>{html.escape(title)}</h1><p class='subtitle'>{html.escape(subtitle)}</p>"
            f"<div class='date-mark'><div class='date-number'>{today:%m.%d}</div>"
            f"<div class='date-week'>周{week} / {today.year}</div></div></div>")


def section_heading(title, subtitle="", ident=""):
    ident_attr = f" id='{html.escape(ident, quote=True)}'" if ident else ""
    return (f"<div class='section-heading'{ident_attr}><h2>{html.escape(title)}</h2>"
            + (f"<p>{html.escape(subtitle)}</p>" if subtitle else "") + "</div>")


def display_title(title):
    value = re.sub(r"^\d{4}-\d{2}-\d{2}[｜|·\s]+", "", title).strip()
    return re.sub(r"[（(]预览[）)]$", "", value).strip() or title


def reading_minutes(text):
    chinese = len(re.findall(r"[\u3400-\u9fff]", text))
    words = len(re.findall(r"\b[A-Za-z]+\b", re.sub(r"https?://\S+", "", text)))
    return max(1, math.ceil(chinese / 300 + words / 180))


def message_cover(message):
    timestamp = local_date(message["created"])
    date_text = timestamp.strftime("今日 %H:%M" if timestamp.date() == local_date().date() else "%m.%d %H:%M")
    kind = "新闻简报" if message["delivery_id"].startswith("kindle-news-") else "Muse 来信"
    if "-preview-" in message["delivery_id"]:
        kind += " / 试阅"
    topics = list(dict.fromkeys(re.findall(r"【([^】\n]{1,16})】", message["text"])))[:4]
    minutes = reading_minutes(message["text"])
    topic_line = (f"<p class='cover-topics'>{html.escape(' / '.join(topics))}<span class='reading-time'>约 {minutes} 分钟阅读</span></p>" if topics
                  else f"<p class='cover-details'>约 {minutes} 分钟阅读</p>")
    return (f"<article class='cover'><div class='cover-top'><span class='cover-kind'>最新来信 / {kind}</span>"
            f"<time class='cover-time' datetime='{timestamp.isoformat()}'>{date_text}</time></div>"
            f"<h2>{html.escape(display_title(message['title']))}</h2>{topic_line}"
            f"<div class='cover-footer'><a class='button primary' href='/message/{message['id']}'>阅读最新消息</a></div></article>")


def empty_state(title, text, action="", url=""):
    button = f"<a class='button' href='{url}'>{html.escape(action)}</a>" if action else ""
    return f"<div class='empty'><h2>{html.escape(title)}</h2><p>{html.escape(text)}</p>{button}</div>"


def answer_html(text):
    # Markup only: textContent retains the exact stored text and every newline.
    result = []
    for line in text.splitlines(keepends=True):
        value = line.strip()
        css = ("text-blank" if not value else "text-section" if re.fullmatch(r"【[^】]+】", value) else
               "text-source" if "https://" in value or "http://" in value else
               "text-heading" if re.match(r"^\d+[、.．]", value) else
               "text-intro" if value.startswith(("北京时间", "——")) else "")
        escaped = html.escape(line)
        result.append(f"<span class='text-line{(' ' + css) if css else ''}'>{escaped}</span>")
    return "<div class='answer'>" + "".join(result) + "</div>"


def reading_heading(title, label, timestamp=None):
    meta = f"<p class='meta'>{received_time(timestamp)} · 北京时间</p>" if timestamp is not None else ""
    return (f"<header class='reading-heading'><p class='reading-label'>{html.escape(label)}</p>"
            f"<h1>{html.escape(display_title(title))}</h1>{meta}</header>")


def reading_progress(page, count):
    return (f"<p class='reading-meta'>第 {page + 1} / {count} 页</p>"
            f"<progress class='reading-progress' value='{page + 1}' max='{count}' aria-label='阅读页数'></progress>")


def pager(base, page, count):
    def link(index):
        return html.escape(base + ('&' if '?' in base else '?') + f'page={index}', quote=True)
    previous = (f"<a class='button' href='{link(page - 1)}'>上一页</a>" if page else
                "<span class='button disabled' aria-disabled='true'>上一页</span>")
    following = (f"<a class='button primary' href='{link(page + 1)}'>下一页</a>" if page + 1 < count else
                 "<span class='button disabled' aria-disabled='true'>下一页</span>")
    return (f"<nav class='pager' aria-label='阅读翻页'><div class='pager-side'>{previous}</div>"
            f"<div class='pager-count'>{page + 1} / {count}</div><div class='pager-side'>{following}</div></nav>")


def news_sync_note(state):
    if not state['last_success']:
        text = state['error'] or '正在同步最新 AI 资讯，稍后自动更新。'
        return f"<div class='notice'>{html.escape(text)}</div>"
    notice = f"<div class='notice'>{html.escape(state['error'])}</div>" if state['error'] else ''
    return (notice + f"<p class='sync-line'>更新于 {received_time(state['last_success'])} · "
            "<a href='https://aihot.news/'>AIHOT</a></p>")


def news_item(row, mode, topic='selected'):
    category = CATEGORY_LABELS.get(row.get('category'), '')
    prefix = category + ' / ' if category else ''
    return (f"<article class='item'><a href='/ai-news/{row['id']}?mode={mode}&amp;topic={topic}'>{html.escape(row['title'])}</a>"
            f"<div class='meta'>{prefix}{html.escape(row['source'])}<br>收录 {received_time(row['discovered_at'])}</div></article>")


def news_feature(row, mode, topic='selected'):
    category = CATEGORY_LABELS.get(row.get('category'), '最新资讯')
    snippet = row['summary'][:80] + ('…' if len(row['summary']) > 80 else '')
    url = f"/ai-news/{row['id']}?mode={mode}&amp;topic={topic}"
    return (f"<article class='news-lead'><p class='news-category'>{category}</p>"
            f"<h2><a href='{url}'>{html.escape(row['title'])}</a></h2>"
            f"<p class='news-summary'>{html.escape(snippet)}</p>"
            f"<p class='meta'>{html.escape(row['source'])}<br>收录 {received_time(row['discovered_at'])}</p>"
            f"<a class='button primary' href='{url}'>阅读摘要</a></article>")


def topic_navigation(base, mode, topic):
    links = []
    for key, (label, _) in NEWS_TOPICS.items():
        current = " aria-current='page'" if key == topic else ''
        links.append(f"<a href='{html.escape(base + '?mode=' + mode + '&topic=' + key, quote=True)}'{current}>{label}</a>")
    return "<nav class='topic-nav' aria-label='资讯分类'>" + ''.join(links) + '</nav>'


def news_text(row):
    text = row['summary'] or '这条资讯未附摘要，可通过下方来源链接阅读。'
    if row['reason']:
        text += '\n\n推荐理由：\n' + row['reason']
    return text


def news_provenance(row):
    published = received_time(row['published_at']) if row['published_at'] is not None else '来源未提供'
    original = (f"<a class='text-link' href='{html.escape(row['original_url'], quote=True)}'>原始报道</a>"
                if row['original_url'] else '')
    return (f"<div class='utility-nav'><p class='meta'>信源：{html.escape(row['source'])}</p>"
            f"<p class='meta'>原文发布时间：{published}<br>站点收录时间：{received_time(row['discovered_at'])}<br>时间均为北京时间</p>"
            f"<a class='text-link' href='{html.escape(row['aihot_url'], quote=True)}'>AIHOT 阅读页</a>{original}</div>")
