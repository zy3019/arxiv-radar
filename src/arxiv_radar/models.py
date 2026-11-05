"""Data shapes shared across the pipeline."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field


class Paper(BaseModel):
    id: str  # arXiv id without the version suffix, e.g. 2611.06914
    title: str
    abstract: str
    authors: list[str]
    categories: list[str]
    published: dt.datetime
    url: str
    pdf_url: str


class Review(BaseModel):
    """The LLM's structured reading of one paper. Doubles as the output schema."""

    score: int = Field(description="Relevance to the researcher, 1 to 10.")
    title_translated: str = Field(description="The paper title in the output language.")
    tldr: str = Field(description="One sentence: what the paper does and why it matters.")
    method: str = Field(description="The approach, in one or two sentences.")
    findings: str = Field(
        description="Main results in one or two sentences, using only what the abstract states."
    )
    why_relevant: str = Field(
        description="One sentence linking the paper to the researcher's interests."
    )
    tags: list[str] = Field(description="Two to four short topic tags.")


class Entry(BaseModel):
    paper: Paper
    lexical_score: float
    review: Review | None = None


class Digest(BaseModel):
    date: dt.date
    fetched: int  # new papers considered
    matched: int  # papers that passed the keyword ranking
    entries: list[Entry]

    @property
    def has_reviews(self) -> bool:
        return any(entry.review for entry in self.entries)
