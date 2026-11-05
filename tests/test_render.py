import datetime as dt
import xml.etree.ElementTree as ET

from arxiv_radar import store
from arxiv_radar.models import Digest, Entry
from arxiv_radar.render import build_site

from conftest import make_paper, make_review

ATOM = "{http://www.w3.org/2005/Atom}"


def save(config, date, entries, fetched=10, matched=5):
    store.save_digest(
        config.data_dir, Digest(date=date, fetched=fetched, matched=matched, entries=entries)
    )


def read(config, name):
    return (config.site_dir / name).read_text(encoding="utf-8")


def test_index_shows_the_latest_digest_and_links_the_archive(config):
    older, newer = dt.date(2026, 11, 4), dt.date(2026, 11, 5)
    save(config, older, [Entry(paper=make_paper("old", title="Older paper"), lexical_score=1)])
    save(config, newer, [Entry(paper=make_paper("new", title="Newer paper"), lexical_score=1)])

    assert build_site(config) == 2

    index = read(config, "index.html")
    assert "Newer paper" in index
    assert "Older paper" not in index
    assert 'href="2026-11-04.html"' in index
    assert "Older paper" in read(config, "2026-11-04.html")


def test_reviewed_paper_shows_summary_and_score(config):
    entry = Entry(paper=make_paper(title="Original"), lexical_score=1, review=make_review(9))
    save(config, dt.date(2026, 11, 5), [entry])

    build_site(config)

    page = read(config, "index.html")
    assert "一个标题" in page
    assert "一句话总结。" in page
    assert "Original" in page
    assert '<div class="score high">9</div>' in page
    assert "没有使用 AI" not in page


def test_digest_without_reviews_shows_a_notice(config):
    save(config, dt.date(2026, 11, 5), [Entry(paper=make_paper(), lexical_score=1)])

    build_site(config)

    assert "没有使用 AI" in read(config, "index.html")


def test_page_counts_the_funnel(config):
    save(config, dt.date(2026, 11, 5), [Entry(paper=make_paper(), lexical_score=1)], 412, 37)

    build_site(config)

    assert "新论文 412 篇，关键词命中 37 篇，入选 1 篇" in read(config, "index.html")


def test_english_labels(config):
    config.language = "en"
    save(config, dt.date(2026, 11, 5), [Entry(paper=make_paper(), lexical_score=1)])

    build_site(config)

    page = read(config, "index.html")
    assert '<html lang="en">' in page
    assert "built without AI" in page


def test_paper_text_is_escaped(config):
    hostile = "<script>alert(1)</script> & more"
    review = make_review()
    review.tldr = hostile
    entry = Entry(paper=make_paper(title=hostile, abstract=hostile), lexical_score=1, review=review)
    save(config, dt.date(2026, 11, 5), [entry])

    build_site(config)

    assert "<script>" not in read(config, "index.html")
    ET.fromstring(read(config, "feed.xml"))  # still well-formed XML


def test_feed_is_valid_atom_with_absolute_links(config):
    entry = Entry(paper=make_paper("2611.00001"), lexical_score=1, review=make_review())
    save(config, dt.date(2026, 11, 5), [entry])

    build_site(config, "https://someone.github.io/radar/")

    feed = ET.fromstring(read(config, "feed.xml"))
    assert feed.tag == f"{ATOM}feed"
    self_link = feed.find(f"{ATOM}link[@rel='self']")
    assert self_link.attrib["href"] == "https://someone.github.io/radar/feed.xml"
    item = feed.find(f"{ATOM}entry")
    assert item.findtext(f"{ATOM}title") == "一个标题"
    assert item.find(f"{ATOM}link").attrib["href"] == "https://arxiv.org/abs/2611.00001"


def test_empty_site_still_builds(config):
    assert build_site(config) == 0

    assert "还没有数据" in read(config, "index.html")
    ET.fromstring(read(config, "feed.xml"))


def test_day_with_no_matches_says_so(config):
    save(config, dt.date(2026, 11, 5), [], matched=0)

    build_site(config)

    assert "今天没有符合条件的论文" in read(config, "index.html")


def test_rebuild_removes_stale_pages(config):
    save(config, dt.date(2026, 11, 5), [])
    config.site_dir.mkdir(parents=True)
    (config.site_dir / "2020-01-01.html").write_text("stale")

    build_site(config)

    assert not (config.site_dir / "2020-01-01.html").exists()
