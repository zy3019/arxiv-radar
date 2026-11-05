from arxiv_radar.rank import rank, tokenize

from conftest import make_paper


def ids(ranked):
    return [paper.id for paper, _ in ranked]


def test_tokenize_lowercases_splits_hyphens_and_strips_plurals():
    assert tokenize("Retrieval-Augmented LLM Agents of the class") == [
        "retrieval",
        "augmented",
        "llm",
        "agent",
        "class",
    ]


def test_papers_without_a_keyword_are_dropped():
    papers = [
        make_paper("match", abstract="We study retrieval for question answering."),
        make_paper("other", abstract="We study protein folding."),
    ]
    assert ids(rank(papers, ["retrieval"])) == ["match"]


def test_title_match_beats_abstract_match():
    filler = "We describe a system and report its measured behaviour in detail."
    papers = [
        make_paper("abstract", title="A system", abstract=f"{filler} It uses retrieval."),
        make_paper("title", title="Retrieval systems", abstract=f"{filler} It works well."),
        make_paper("neither", title="Other", abstract=filler),
    ]
    assert ids(rank(papers, ["retrieval"])) == ["title", "abstract"]


def test_exact_phrase_beats_scattered_words():
    papers = [
        make_paper("phrase", abstract="We improve retrieval-augmented generation pipelines."),
        make_paper("scattered", abstract="Retrieval of text, then image generation, augmented."),
    ]
    assert ids(rank(papers, ["retrieval-augmented generation"])) == ["phrase", "scattered"]


def test_exclude_keywords_remove_papers():
    papers = [
        make_paper("keep", abstract="Retrieval for text."),
        make_paper("drop", abstract="Retrieval for medical imaging."),
    ]
    assert ids(rank(papers, ["retrieval"], ["medical imaging"])) == ["keep"]


def test_empty_input():
    assert rank([], ["retrieval"]) == []
