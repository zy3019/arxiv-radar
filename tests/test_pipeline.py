import datetime as dt
import json

import anthropic
import httpx2
import pytest

from arxiv_radar import store
from arxiv_radar.pipeline import run

from conftest import make_paper, make_review

TODAY = dt.date(2026, 11, 5)
NOW = dt.datetime(2026, 11, 5, tzinfo=dt.timezone.utc)


class FakeReviewer:
    def __init__(self, scores):
        self.scores = scores  # paper id -> score, or None for a failed review
        self.seen = []

    def review_all(self, papers):
        self.seen.extend(paper.id for paper in papers)
        return {
            paper.id: make_review(self.scores[paper.id])
            for paper in papers
            if self.scores.get(paper.id) is not None
        }


def fetcher(*papers):
    return lambda categories, since, max_results: list(papers)


def matching(paper_id):
    return make_paper(paper_id, abstract="A retrieval system.")


def test_lexical_mode_builds_digest_without_reviews(config):
    papers = [matching("a"), matching("b"), matching("c"), make_paper("off", abstract="Proteins.")]
    digest = run(config, None, now=NOW, today=TODAY, fetcher=fetcher(*papers))

    assert (digest.fetched, digest.matched) == (4, 3)
    assert len(digest.entries) == config.max_papers
    assert not digest.has_reviews


def test_llm_mode_filters_by_score_and_sorts(config):
    reviewer = FakeReviewer({"a": 6, "b": 9, "c": 3})
    papers = [matching("a"), matching("b"), matching("c")]

    digest = run(config, reviewer, now=NOW, today=TODAY, fetcher=fetcher(*papers))

    assert [entry.paper.id for entry in digest.entries] == ["b", "a"]


def test_only_top_candidates_reach_the_llm(config):
    reviewer = FakeReviewer({})
    papers = [matching(str(i)) for i in range(10)]

    run(config, reviewer, now=NOW, today=TODAY, fetcher=fetcher(*papers))

    assert len(reviewer.seen) == config.max_candidates


def test_paper_with_failed_review_is_kept_after_reviewed_ones(config):
    reviewer = FakeReviewer({"a": None, "b": 7})
    papers = [matching("a"), matching("b")]

    digest = run(config, reviewer, now=NOW, today=TODAY, fetcher=fetcher(*papers))

    assert [entry.paper.id for entry in digest.entries] == ["b", "a"]
    assert digest.entries[1].review is None


def test_seen_papers_are_not_processed_twice(config):
    reviewer = FakeReviewer({"a": 8, "b": 8})

    run(config, reviewer, now=NOW, today=TODAY, fetcher=fetcher(matching("a")))
    tomorrow = TODAY + dt.timedelta(days=1)
    digest = run(
        config, reviewer, now=NOW, today=tomorrow, fetcher=fetcher(matching("a"), matching("b"))
    )

    assert reviewer.seen == ["a", "b"]
    assert [entry.paper.id for entry in digest.entries] == ["b"]


def test_returns_none_and_keeps_digest_when_nothing_is_new(config):
    run(config, None, now=NOW, today=TODAY, fetcher=fetcher(matching("a")))

    result = run(config, None, now=NOW, today=TODAY, fetcher=fetcher(matching("a")))

    assert result is None
    assert len(store.load_digest(config.data_dir, TODAY).entries) == 1


def test_second_run_on_the_same_day_merges(config):
    reviewer = FakeReviewer({"a": 7, "b": 9})

    run(config, reviewer, now=NOW, today=TODAY, fetcher=fetcher(matching("a")))
    digest = run(config, reviewer, now=NOW, today=TODAY, fetcher=fetcher(matching("b")))

    assert [entry.paper.id for entry in digest.entries] == ["b", "a"]
    assert digest.fetched == 2


def test_digest_is_saved_when_no_paper_matches(config):
    papers = [make_paper("off", abstract="Proteins.")]
    digest = run(config, None, now=NOW, today=TODAY, fetcher=fetcher(*papers))

    assert digest.entries == []
    assert store.load_digest(config.data_dir, TODAY) is not None


def test_failed_run_leaves_papers_unseen_so_it_can_be_repeated(config):
    class BrokenReviewer:
        def review_all(self, papers):
            request = httpx2.Request("POST", "https://api.test")
            raise anthropic.AuthenticationError(
                "bad key", response=httpx2.Response(401, request=request), body=None
            )

    with pytest.raises(anthropic.AuthenticationError):
        run(config, BrokenReviewer(), now=NOW, today=TODAY, fetcher=fetcher(matching("a")))

    assert store.load_seen(config.data_dir) == {}
    assert run(config, None, now=NOW, today=TODAY, fetcher=fetcher(matching("a"))) is not None


def test_lookback_window_is_passed_to_the_fetcher(config):
    calls = []

    def recording_fetcher(categories, since, max_results):
        calls.append((categories, since, max_results))
        return []

    run(config, None, now=NOW, today=TODAY, fetcher=recording_fetcher)

    assert calls == [(["cs.CL"], NOW - dt.timedelta(days=5), config.max_fetch)]


def test_seen_file_drops_old_ids(config):
    seen = {"old": "2026-09-01", "recent": "2026-11-01"}
    store.save_seen(config.data_dir, seen, TODAY)

    assert json.loads((config.data_dir / "seen.json").read_text()) == {"recent": "2026-11-01"}
