"""Build the static site from saved digests: one page per day, an index and an Atom feed."""

from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import Config
from .models import Digest
from .store import load_all_digests

FEED_DIGESTS = 7
ARCHIVE_LINKS = 30

LABELS = {
    "zh": {
        "html_lang": "zh-CN",
        "method": "方法",
        "findings": "结果",
        "why_relevant": "为什么推荐",
        "abstract": "原文摘要",
        "no_review": "未生成 AI 摘要",
        "funnel": "新论文 {fetched} 篇，关键词命中 {matched} 篇，入选 {shown} 篇",
        "empty_day": "今天没有符合条件的论文。",
        "empty_site": "还没有数据，运行一次 arxiv-radar run 后这里就会出现内容。",
        "no_llm_banner": "这一期没有使用 AI：论文只按关键词排序，也没有中文摘要。"
        "配置 LLM_API_KEY 后即可开启。",
        "archive": "往期",
        "feed": "RSS 订阅",
        "credit": "感谢 arXiv 开放其数据接口。AI 摘要可能有误，请以原文为准。",
    },
    "en": {
        "html_lang": "en",
        "method": "Method",
        "findings": "Findings",
        "why_relevant": "Why it's here",
        "abstract": "Abstract",
        "no_review": "No AI summary",
        "funnel": "{fetched} new papers, {matched} keyword matches, {shown} shown",
        "empty_day": "No papers met the bar today.",
        "empty_site": "No data yet. Run arxiv-radar run and this page will fill in.",
        "no_llm_banner": "This issue was built without AI: papers are ranked by keyword "
        "and have no summaries. Set LLM_API_KEY to turn it on.",
        "archive": "Archive",
        "feed": "RSS feed",
        "credit": "Thank you to arXiv for use of its open access interoperability. "
        "AI summaries can be wrong; check the paper.",
    },
}


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _render_page(env: Environment, config: Config, digest: Digest | None, dates: list) -> str:
    labels = LABELS[config.language]
    funnel = None
    if digest:
        funnel = labels["funnel"].format(
            fetched=digest.fetched, matched=digest.matched, shown=len(digest.entries)
        )
    return env.get_template("page.html").render(
        title=config.site_title, digest=digest, dates=dates, labels=labels, funnel=funnel
    )


def build_site(config: Config, site_url: str = "") -> int:
    """Write the site and return the number of daily pages."""
    digests = load_all_digests(config.data_dir)
    env = _environment()
    site_dir = config.site_dir
    if site_dir.exists():
        shutil.rmtree(site_dir)
    site_dir.mkdir(parents=True)

    dates = [digest.date for digest in digests[:ARCHIVE_LINKS]]
    for digest in digests:
        page = _render_page(env, config, digest, dates)
        (site_dir / f"{digest.date.isoformat()}.html").write_text(page, encoding="utf-8")
    latest = digests[0] if digests else None
    (site_dir / "index.html").write_text(
        _render_page(env, config, latest, dates), encoding="utf-8"
    )

    entries = [
        (digest.date, entry) for digest in digests[:FEED_DIGESTS] for entry in digest.entries
    ]
    updated = digests[0].date if digests else dt.date(1970, 1, 1)
    feed = env.get_template("feed.xml").render(
        title=config.site_title,
        site_url=site_url.rstrip("/"),
        entries=entries,
        updated=updated,
        labels=LABELS[config.language],
    )
    (site_dir / "feed.xml").write_text(feed, encoding="utf-8")
    return len(digests)
