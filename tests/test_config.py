from pathlib import Path

from arxiv_radar.config import LLMConfig, load_config


def test_shipped_config_loads_and_uses_deepseek():
    config = load_config(Path(__file__).parent.parent / "config.yaml")

    assert config.llm.provider == "openai"
    assert config.llm.base_url == "https://api.deepseek.com"
    assert config.llm.model == "deepseek-flash"
    assert config.llm.extra_body == {"thinking": {"type": "disabled"}}


def test_defaults_are_deepseek():
    llm = LLMConfig()

    assert (llm.provider, llm.base_url, llm.model) == (
        "openai",
        "https://api.deepseek.com",
        "deepseek-flash",
    )
    assert llm.api_key_env == "LLM_API_KEY"


def test_anthropic_gets_claude_defaults():
    llm = LLMConfig(provider="anthropic")

    assert llm.base_url is None
    assert llm.model == "claude-opus-5-5"
    assert llm.extra_body == {}


def test_anthropic_settings_still_override_defaults():
    llm = LLMConfig(provider="anthropic", model="claude-haiku-5-5", base_url="https://x.test")

    assert (llm.model, llm.base_url) == ("claude-haiku-5-5", "https://x.test")
