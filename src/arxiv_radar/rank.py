"""Free first-pass ranking: BM25 over titles and abstracts, plus a bonus for exact phrases.

arXiv publishes hundreds of papers a day in the busiest categories. This step decides
which few reach the LLM, so it keeps the API cost independent of arXiv's volume.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence

from .models import Paper

K1 = 1.5
B = 0.75
TITLE_WEIGHT = 2  # a title word counts as this many abstract words
PHRASE_BONUS = 3.0

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset(
    "a an and are as at be by for from in into is it of on or that the this to with".split()
)


def tokenize(text: str) -> list[str]:
    tokens = []
    for token in TOKEN_PATTERN.findall(text.lower()):
        if token in STOPWORDS:
            continue
        # Enough stemming to match "agents" with "agent".
        if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]
        tokens.append(token)
    return tokens


def _contains_phrase(tokens: list[str], phrase: list[str]) -> bool:
    return f" {' '.join(phrase)} " in f" {' '.join(tokens)} "


def rank(
    papers: list[Paper], keywords: Sequence[str], exclude_keywords: Sequence[str] = ()
) -> list[tuple[Paper, float]]:
    """Return (paper, score) pairs for papers matching a keyword, best first."""
    excluded = [tokenize(keyword) for keyword in exclude_keywords]
    documents = []
    for paper in papers:
        title = tokenize(paper.title)
        abstract = tokenize(paper.abstract)
        full_text = title + abstract
        if not any(_contains_phrase(full_text, phrase) for phrase in excluded if phrase):
            documents.append((paper, title, abstract, title * TITLE_WEIGHT + abstract))
    if not documents:
        return []

    phrases = [phrase for phrase in map(tokenize, keywords) if phrase]
    terms = {term for phrase in phrases for term in phrase}
    average_length = sum(len(doc[3]) for doc in documents) / len(documents)
    document_frequency = Counter(
        term for doc in documents for term in terms.intersection(doc[3])
    )
    total = len(documents)
    idf = {
        term: math.log(1 + (total - count + 0.5) / (count + 0.5))
        for term, count in document_frequency.items()
    }

    scored = []
    for paper, title, abstract, weighted in documents:
        counts = Counter(weighted)
        length_norm = 1 - B + B * len(weighted) / average_length
        score = sum(
            weight * counts[term] * (K1 + 1) / (counts[term] + K1 * length_norm)
            for term, weight in idf.items()
            if counts[term]
        )
        # Multi-word keywords are what the user actually typed, so an exact hit counts extra.
        score += PHRASE_BONUS * sum(
            _contains_phrase(title, phrase) or _contains_phrase(abstract, phrase)
            for phrase in phrases
            if len(phrase) > 1
        )
        if score > 0:
            scored.append((paper, round(score, 3)))
    scored.sort(key=lambda pair: (-pair[1], pair[0].id))
    return scored
