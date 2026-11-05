import datetime as dt
import urllib.error
import urllib.parse

import pytest

from arxiv_radar.fetch import PAGE_SIZE, ArxivError, fetch_recent, parse_feed

UTC = dt.timezone.utc


def entry(paper_id, published="2026-11-04T18:58:23Z"):
    return f"""
  <entry>
    <id>http://arxiv.org/abs/{paper_id}</id>
    <title>A Framework
      for Testing</title>
    <updated>{published}</updated>
    <link href="https://arxiv.org/abs/{paper_id}" rel="alternate" type="text/html"/>
    <summary>  First line
      second line. </summary>
    <category term="cs.MA" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.CL" scheme="http://arxiv.org/schemas/atom"/>
    <published>{published}</published>
    <arxiv:primary_category term="cs.MA"/>
    <author><name>Ada Lovelace</name></author>
    <author><name>Alan Turing</name></author>
  </entry>"""


def feed(*entries, total=None):
    total = len(entries) if total is None else total
    return f"""<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
      xmlns:arxiv="http://arxiv.org/schemas/atom" xmlns="http://www.w3.org/2005/Atom">
  <opensearch:totalResults>{total}</opensearch:totalResults>
  {"".join(entries)}
</feed>""".encode()


def test_parse_feed_extracts_fields():
    papers, total = parse_feed(feed(entry("2611.06914v2"), total=124696))
    paper = papers[0]
    assert total == 124696
    assert paper.id == "2611.06914"
    assert paper.title == "A Framework for Testing"
    assert paper.abstract == "First line second line."
    assert paper.authors == ["Ada Lovelace", "Alan Turing"]
    assert paper.categories == ["cs.MA", "cs.CL"]
    assert paper.published == dt.datetime(2026, 11, 4, 18, 58, 23, tzinfo=UTC)
    assert paper.url == "https://arxiv.org/abs/2611.06914"


def test_parse_feed_keeps_old_style_ids():
    papers, _ = parse_feed(feed(entry("cs/0112017v1")))
    assert papers[0].id == "cs/0112017"


def test_parse_feed_raises_on_api_error_entry():
    error = """<entry><id>http://arxiv.org/api/errors#bad</id>
      <title>Error</title><summary>incorrect id format</summary></entry>"""
    with pytest.raises(ArxivError, match="incorrect id format"):
        parse_feed(feed(error))


def test_fetch_recent_stops_at_cutoff_and_filters():
    since = dt.datetime(2026, 11, 3, tzinfo=UTC)
    urls = []

    def get(url):
        urls.append(url)
        return feed(
            entry("2611.00002v1", "2026-11-04T00:00:00Z"),
            entry("2611.00001v1", "2026-11-01T00:00:00Z"),
        )

    papers = fetch_recent(["cs.CL", "cs.LG"], since, 1000, get=get, sleep=lambda _: None)

    assert [paper.id for paper in papers] == ["2611.00002"]
    assert len(urls) == 1
    query = urllib.parse.parse_qs(urllib.parse.urlparse(urls[0]).query)
    assert query["search_query"] == ["cat:cs.CL OR cat:cs.LG"]
    assert query["sortBy"] == ["submittedDate"]


def test_fetch_recent_paginates_and_waits_between_pages():
    since = dt.datetime(2026, 1, 1, tzinfo=UTC)
    pages = [
        feed(*[entry(f"2611.{i:05d}v1") for i in range(PAGE_SIZE)]),
        feed(entry("2611.99999v1")),
    ]
    sleeps = []

    papers = fetch_recent(
        ["cs.CL"], since, 1000, get=lambda url: pages.pop(0), sleep=sleeps.append
    )

    assert len(papers) == PAGE_SIZE + 1
    assert sleeps == [3.0]


def test_fetch_recent_retries_transient_failures():
    since = dt.datetime(2026, 1, 1, tzinfo=UTC)
    replies = [
        urllib.error.HTTPError("url", 503, "busy", None, None),
        feed(total=10),  # the API's spurious empty page
        feed(entry("2611.00001v1")),
    ]

    def get(url):
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    papers = fetch_recent(["cs.CL"], since, 100, get=get, sleep=lambda _: None)
    assert [paper.id for paper in papers] == ["2611.00001"]


def test_fetch_recent_gives_up_after_repeated_failures():
    def get(url):
        raise urllib.error.HTTPError("url", 503, "busy", None, None)

    since = dt.datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ArxivError, match="HTTP 503"):
        fetch_recent(["cs.CL"], since, 100, get=get, sleep=lambda _: None)


def test_fetch_recent_does_not_retry_client_errors():
    calls = []

    def get(url):
        calls.append(url)
        raise urllib.error.HTTPError("url", 400, "bad", None, None)

    since = dt.datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ArxivError, match="HTTP 400"):
        fetch_recent(["cs.CL"], since, 100, get=get, sleep=lambda _: None)
    assert len(calls) == 1
