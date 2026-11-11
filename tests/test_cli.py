import yaml

from arxiv_radar import cli
from arxiv_radar.fetch import ArxivError
from arxiv_radar.llm import LLMError, OpenAICompatibleReviewer


def write_config(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "categories": ["cs.CL"],
                "interests": "RAG",
                "keywords": ["retrieval"],
                "data_dir": str(tmp_path / "data"),
                "site_dir": str(tmp_path / "site"),
            }
        ),
        encoding="utf-8",
    )
    return path


def stub_run(monkeypatch, result=None):
    calls = []

    def fake_run(config, reviewer):
        calls.append(reviewer)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(cli, "run", fake_run)
    return calls


def test_run_without_a_key_falls_back_to_keywords(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    calls = stub_run(monkeypatch)

    assert cli.main(["--config", str(write_config(tmp_path)), "run"]) == 0

    assert calls == [None]
    assert (tmp_path / "site" / "index.html").exists()


def test_run_with_a_key_uses_the_reviewer(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    calls = stub_run(monkeypatch)

    assert cli.main(["--config", str(write_config(tmp_path)), "run"]) == 0

    assert isinstance(calls[0], OpenAICompatibleReviewer)


def test_no_llm_flag_wins_over_a_key(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    calls = stub_run(monkeypatch)

    assert cli.main(["--config", str(write_config(tmp_path)), "run", "--no-llm"]) == 0

    assert calls == [None]


def test_arxiv_failure_exits_nonzero(tmp_path, monkeypatch):
    stub_run(monkeypatch, ArxivError("down"))

    assert cli.main(["--config", str(write_config(tmp_path)), "run"]) == 1


def test_build_does_not_fetch(tmp_path, monkeypatch):
    calls = stub_run(monkeypatch)

    assert cli.main(["--config", str(write_config(tmp_path)), "build"]) == 0

    assert calls == []


def test_llm_failure_exits_nonzero(tmp_path, monkeypatch):
    stub_run(monkeypatch, LLMError("bad key"))

    assert cli.main(["--config", str(write_config(tmp_path)), "run"]) == 1
