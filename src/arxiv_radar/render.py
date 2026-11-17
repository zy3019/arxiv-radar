"""Build the static site from saved digests: one page per day, an index, a page listing
every paper so far, and an Atom feed."""

from __future__ import annotations

import datetime as dt
import shutil
from collections import Counter
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import Config
from .models import Digest, Entry
from .store import load_all_digests

FEED_DIGESTS = 7
ARCHIVE_LINKS = 30
TAG_CHIPS = 20  # most common tags offered as one-click filters on the all-papers page

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
        "latest": "最新一期",
        "all_papers": "全部论文",
        "all_summary": "共 {papers} 篇，来自 {issues} 期",
        "issue": "{date} 期",
        "search": "搜索标题、总结、标签或作者",
        "score": "评分",
        "any_score": "全部评分",
        "score_at_least": "{n} 分及以上",
        "sort": "排序",
        "newest_first": "最新在前",
        "best_first": "评分最高在前",
        "showing": "显示 {shown} / {total} 篇",
        "tag_filter": "标签：{tag}",
        "clear_filters": "清除筛选",
        "common_tags": "常见标签",
        "no_match": "没有符合条件的论文。",
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
        "latest": "Latest",
        "all_papers": "All papers",
        "all_summary": "{papers} papers from {issues} issues",
        "issue": "{date} issue",
        "search": "Search titles, summaries, tags or authors",
        "score": "Score",
        "any_score": "Any score",
        "score_at_least": "{n} and up",
        "sort": "Order",
        "newest_first": "Newest first",
        "best_first": "Highest score first",
        "showing": "Showing {shown} of {total}",
        "tag_filter": "tag: {tag}",
        "clear_filters": "Clear filters",
        "common_tags": "Common tags",
        "no_match": "No papers match.",
    },
}


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _render_page(
    env: Environment, config: Config, digest: Digest | None, dates: list, current: str = ""
) -> str:
    labels = LABELS[config.language]
    funnel = None
    if digest:
        funnel = labels["funnel"].format(
            fetched=digest.fetched, matched=digest.matched, shown=len(digest.entries)
        )
    return env.get_template("page.html").render(
        title=config.site_title,
        digest=digest,
        dates=dates,
        labels=labels,
        funnel=funnel,
        current=current,
    )


def _tag_key(tag: str) -> str:
    # Matches norm() in papers.html: the model writes "Agent 评测" one day, "agent评测" the next.
    return "".join(tag.split()).lower()


def _all_papers(digests: list[Digest]) -> list[tuple[dt.date, Entry]]:
    """Every paper shown so far, newest issue first, each paper once."""
    seen: set[str] = set()
    items = []
    for digest in digests:
        for entry in digest.entries:
            if entry.paper.id not in seen:
                seen.add(entry.paper.id)
                items.append((digest.date, entry))
    return items


def _common_tags(items: list[tuple[dt.date, Entry]]) -> list[tuple[str, int]]:
    """Tags on at least two papers, most common first, spelled as first seen."""
    counts: Counter[str] = Counter()
    names: dict[str, str] = {}
    for _, entry in items:
        keys = set()
        for tag in entry.review.tags if entry.review else []:
            key = _tag_key(tag)
            if key:
                keys.add(key)
                names.setdefault(key, tag.strip())
        counts.update(keys)
    return [(names[key], count) for key, count in counts.most_common(TAG_CHIPS) if count >= 2]


def _render_papers(env: Environment, config: Config, digests: list[Digest], dates: list) -> str:
    labels = LABELS[config.language]
    items = _all_papers(digests)
    scores = [entry.review.score if entry.review else 0 for _, entry in items]
    # Only offer thresholds that would hide something.
    thresholds = sorted({score for score in scores if score > min(scores)}) if scores else []
    summary = labels["all_summary"].format(
        papers=len(items), issues=len({date for date, _ in items})
    )
    return env.get_template("papers.html").render(
        title=config.site_title,
        dates=dates,
        labels=labels,
        items=items,
        top_tags=_common_tags(items),
        thresholds=thresholds,
        summary=summary,
        current="papers",
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
        _render_page(env, config, latest, dates, current="latest"), encoding="utf-8"
    )
    (site_dir / "papers.html").write_text(
        _render_papers(env, config, digests, dates), encoding="utf-8"
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
