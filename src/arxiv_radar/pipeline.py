"""One daily run: fetch, drop seen papers, rank, review, save."""

from __future__ import annotations

import datetime as dt
import logging

from . import store
from .config import Config
from .fetch import fetch_recent
from .llm import Reviewer
from .models import Digest, Entry
from .rank import rank

log = logging.getLogger(__name__)


def _sort_key(entry: Entry) -> tuple[int, float]:
    # Reviewed papers lead, best score first. Papers with no review follow.
    return (-(entry.review.score if entry.review else 0), -entry.lexical_score)


def _select_entries(
    ranked: list[tuple], config: Config, reviewer: Reviewer | None
) -> list[Entry]:
    if reviewer is None:
        return [
            Entry(paper=paper, lexical_score=score)
            for paper, score in ranked[: config.max_papers]
        ]

    candidates = ranked[: config.max_candidates]
    reviews = reviewer.review_all([paper for paper, _ in candidates])
    log.info("Reviewed %d of %d candidates", len(reviews), len(candidates))
    entries = []
    for paper, score in candidates:
        review = reviews.get(paper.id)
        # A paper with no review may be a declined or failed call, not a weak match, so
        # it stays in the digest without a summary.
        if review is None or review.score >= config.min_score:
            entries.append(Entry(paper=paper, lexical_score=score, review=review))
    return sorted(entries, key=_sort_key)[: config.max_papers]


def run(
    config: Config,
    reviewer: Reviewer | None,
    *,
    now: dt.datetime | None = None,
    today: dt.date | None = None,
    fetcher=fetch_recent,
) -> Digest | None:
    """Run the pipeline. Returns None if arXiv had nothing new since the last run."""
    now = now or dt.datetime.now(dt.timezone.utc)
    today = today or dt.datetime.now().astimezone().date()

    since = now - dt.timedelta(days=config.lookback_days)
    papers = fetcher(config.categories, since, config.max_fetch)
    seen = store.load_seen(config.data_dir)
    fresh = [paper for paper in papers if paper.id not in seen]
    log.info("Fetched %d papers, %d new", len(papers), len(fresh))
    if not fresh:
        return None

    ranked = rank(fresh, config.keywords, config.exclude_keywords)
    log.info("%d papers matched the keywords", len(ranked))
    entries = _select_entries(ranked, config, reviewer)

    digest = Digest(date=today, fetched=len(fresh), matched=len(ranked), entries=entries)
    earlier = store.load_digest(config.data_dir, today)
    if earlier:  # a second run on the same day adds to that day's digest
        digest.fetched += earlier.fetched
        digest.matched += earlier.matched
        digest.entries = sorted(earlier.entries + entries, key=_sort_key)[: config.max_papers]
    store.save_digest(config.data_dir, digest)

    # Saved last, so a run that fails above can simply be repeated.
    seen.update({paper.id: today.isoformat() for paper in fresh})
    store.save_seen(config.data_dir, seen, today)
    return digest
