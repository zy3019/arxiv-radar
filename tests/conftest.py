import datetime as dt

import pytest

from arxiv_radar.config import Config
from arxiv_radar.models import Paper, Review


def make_paper(paper_id="2611.00001", title="A title", abstract="An abstract.", days_old=0):
    return Paper(
        id=paper_id,
        title=title,
        abstract=abstract,
        authors=["Ada Lovelace"],
        categories=["cs.CL"],
        published=dt.datetime(2026, 11, 5, tzinfo=dt.timezone.utc) - dt.timedelta(days=days_old),
        url=f"https://arxiv.org/abs/{paper_id}",
        pdf_url=f"https://arxiv.org/pdf/{paper_id}",
    )


def make_review(score=8):
    return Review(
        score=score,
        title_translated="一个标题",
        tldr="一句话总结。",
        method="方法。",
        findings="结果。",
        why_relevant="与你的兴趣相关。",
        tags=["RAG"],
    )


@pytest.fixture
def config(tmp_path):
    return Config(
        categories=["cs.CL"],
        interests="RAG systems",
        keywords=["retrieval"],
        data_dir=tmp_path / "data",
        site_dir=tmp_path / "site",
        max_candidates=3,
        max_papers=2,
    )
