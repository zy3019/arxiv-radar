import datetime as dt
import json
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

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


def reviewed(paper_id, score=8, tags=("RAG",), title="A title"):
    review = make_review(score)
    review.tags = list(tags)
    return Entry(paper=make_paper(paper_id, title=title), lexical_score=1, review=review)


class PaperItems(HTMLParser):
    """Collect the attributes of each paper on the all-papers page."""

    def __init__(self):
        super().__init__()
        self.items = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "li" and attrs.get("class") == "paper":
            self.items.append(attrs)


def paper_items(page):
    parser = PaperItems()
    parser.feed(page)
    return parser.items


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


def test_tags_survive_the_all_papers_page_intact(config):
    tags = ["<script>alert(1)</script>", "it's \"quoted\" & more"]
    save(config, dt.date(2026, 11, 5), [reviewed("2611.00001", tags=tags)])

    build_site(config)

    page = read(config, "papers.html")
    assert "<script>alert" not in page
    [item] = paper_items(page)
    assert json.loads(item["data-tags"]) == tags


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
    assert "还没有数据" in read(config, "papers.html")
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


def test_all_papers_page_lists_every_issue_newest_first(config):
    save(config, dt.date(2026, 11, 4), [reviewed("old", title="Older paper")])
    save(config, dt.date(2026, 11, 5), [reviewed("new", title="Newer paper")])

    build_site(config)

    page = read(config, "papers.html")
    assert page.index("Newer paper") < page.index("Older paper")
    assert 'href="2026-11-04.html#old"' in page
    assert "共 2 篇，来自 2 期" in page
    assert 'href="papers.html"' in read(config, "index.html")


def test_all_papers_page_shows_a_repeated_paper_once(config):
    save(config, dt.date(2026, 11, 4), [reviewed("same")])
    save(config, dt.date(2026, 11, 5), [reviewed("same")])

    build_site(config)

    page = read(config, "papers.html")
    assert len(paper_items(page)) == 1
    assert 'href="2026-11-05.html#same"' in page


def test_all_papers_page_offers_common_tags_and_useful_score_filters(config):
    entries = [
        reviewed("a", score=6, tags=["RAG", "Agent"]),
        reviewed("b", score=8, tags=["rag ", "Graph", "graph"]),
        reviewed("c", score=9, tags=["Graph"]),
    ]
    save(config, dt.date(2026, 11, 5), entries)

    build_site(config)

    page = read(config, "papers.html")
    chips = re.findall(r'class="chip" data-tag="([^"]*)"[^>]*>[^<]*<span>(\d+)', page)
    assert sorted(chips) == [("Graph", "2"), ("RAG", "2")]
    options = re.findall(r'<option value="(\d+)">', page)
    assert options == ["0", "8", "9"]  # 6 is every paper's score, so it filters nothing


def test_daily_page_links_tags_to_the_all_papers_page(config):
    save(config, dt.date(2026, 11, 5), [reviewed("2611.00001", tags=["Agent 评测"])])

    build_site(config)

    page = read(config, "index.html")
    assert 'href="papers.html?tag=Agent%20%E8%AF%84%E6%B5%8B"' in page
    assert '<article id="2611.00001">' in page


def test_all_papers_page_in_english(config):
    config.language = "en"
    save(config, dt.date(2026, 11, 5), [reviewed("a")])

    build_site(config)

    page = read(config, "papers.html")
    assert "1 papers from 1 issues" in page
    assert "Search titles" in page


def test_no_label_is_hidden_by_a_dict_method():
    # Jinja reads labels.clear as dict.clear, so such a label would print a method.
    from arxiv_radar.render import LABELS

    for labels in LABELS.values():
        assert not [name for name in labels if hasattr(dict, name)]
