"""Fetch recent papers from the arXiv API.

arXiv asks API clients to wait 3 seconds between requests and to use one connection
at a time: https://info.arxiv.org/help/api/tou.html
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable

from . import __version__
from .models import Paper

log = logging.getLogger(__name__)

API_URL = "https://export.arxiv.org/api/query"
USER_AGENT = f"arxiv-radar/{__version__}"
PAGE_SIZE = 200
REQUEST_INTERVAL = 3.0
MAX_ATTEMPTS = 4
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"
OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"

ID_PATTERN = re.compile(r"/abs/(.+?)(?:v\d+)?$")


class ArxivError(RuntimeError):
    pass


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


def parse_feed(xml: bytes) -> tuple[list[Paper], int]:
    """Return the papers in one API response and the query's total result count."""
    root = ET.fromstring(xml)
    papers = []
    for entry in root.iter(f"{ATOM}entry"):
        raw_id = entry.findtext(f"{ATOM}id", "")
        if "/api/errors" in raw_id:
            raise ArxivError(_clean(entry.findtext(f"{ATOM}summary")))
        match = ID_PATTERN.search(raw_id)
        if not match:
            log.warning("Skipping entry with unexpected id: %s", raw_id)
            continue
        paper_id = match.group(1)
        papers.append(
            Paper(
                id=paper_id,
                title=_clean(entry.findtext(f"{ATOM}title")),
                abstract=_clean(entry.findtext(f"{ATOM}summary")),
                authors=[
                    _clean(author.findtext(f"{ATOM}name"))
                    for author in entry.findall(f"{ATOM}author")
                ],
                categories=[
                    category.attrib["term"] for category in entry.findall(f"{ATOM}category")
                ],
                published=dt.datetime.fromisoformat(
                    entry.findtext(f"{ATOM}published", "").replace("Z", "+00:00")
                ),
                url=f"https://arxiv.org/abs/{paper_id}",
                pdf_url=f"https://arxiv.org/pdf/{paper_id}",
            )
        )
    total = int(root.findtext(f"{OPENSEARCH}totalResults", "0"))
    return papers, total


def _http_get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def _fetch_page(
    query: str,
    start: int,
    size: int,
    get: Callable[[str], bytes],
    sleep: Callable[[float], None],
) -> list[Paper]:
    params = urllib.parse.urlencode(
        {
            "search_query": query,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "start": start,
            "max_results": size,
        }
    )
    url = f"{API_URL}?{params}"
    failure = "no attempt made"
    for attempt in range(MAX_ATTEMPTS):
        if attempt:
            sleep(REQUEST_INTERVAL * 2**attempt)
        try:
            papers, total = parse_feed(get(url))
        except urllib.error.HTTPError as error:
            if error.code not in RETRYABLE_STATUS:
                raise ArxivError(f"arXiv API returned HTTP {error.code}") from error
            failure = f"HTTP {error.code}"
        except (urllib.error.URLError, TimeoutError) as error:
            failure = str(error)
        else:
            # The API occasionally returns an empty page for a query that has results.
            if papers or start >= total:
                return papers
            failure = "empty page"
        log.warning("arXiv request failed (%s), attempt %d", failure, attempt + 1)
    raise ArxivError(f"arXiv API failed after {MAX_ATTEMPTS} attempts: {failure}")


def fetch_recent(
    categories: list[str],
    since: dt.datetime,
    max_results: int,
    *,
    get: Callable[[str], bytes] = _http_get,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Paper]:
    """Return papers in these categories first published at or after `since`, newest first."""
    query = " OR ".join(f"cat:{category}" for category in categories)
    papers: dict[str, Paper] = {}
    for start in range(0, max_results, PAGE_SIZE):
        if start:
            sleep(REQUEST_INTERVAL)
        size = min(PAGE_SIZE, max_results - start)
        page = _fetch_page(query, start, size, get, sleep)
        for paper in page:
            if paper.published >= since:
                papers.setdefault(paper.id, paper)
        # Results are sorted newest first, so an old paper means nothing newer remains.
        if len(page) < size or page[-1].published < since:
            return list(papers.values())
    log.warning("Stopped at max_fetch=%d; older papers in the window were skipped", max_results)
    return list(papers.values())
