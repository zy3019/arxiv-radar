"""Load and validate config.yaml. Unknown keys are rejected so typos fail loudly."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class LLMConfig(BaseModel):
    """Which model reviews papers. The defaults are DeepSeek's OpenAI-compatible API."""

    model_config = ConfigDict(extra="forbid")

    # "openai" covers any OpenAI-compatible chat API: DeepSeek, Qwen, Kimi, GLM, OpenAI.
    provider: Literal["openai", "anthropic"] = "openai"
    base_url: str | None = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    api_key_env: str = "LLM_API_KEY"  # the environment variable that holds the key
    max_tokens: int = Field(default=8000, gt=0)
    concurrency: int = Field(default=4, gt=0)
    # Extra request fields for the openai provider. DeepSeek thinks by default, which
    # this task doesn't need, so the default turns it off.
    extra_body: dict[str, Any] = {"thinking": {"type": "disabled"}}

    # anthropic provider only
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    refusal_fallback: bool = True

    @model_validator(mode="before")
    @classmethod
    def _anthropic_defaults(cls, data: Any) -> Any:
        # The DeepSeek defaults would be wrong for Claude, so swap in Claude's own.
        if isinstance(data, dict) and data.get("provider") == "anthropic":
            data = {"base_url": None, "model": "claude-opus-5-5", "extra_body": {}, **data}
        return data


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    categories: list[str] = Field(min_length=1)
    interests: str = Field(min_length=1)
    keywords: list[str] = Field(min_length=1)
    exclude_keywords: list[str] = []
    language: Literal["zh", "en"] = "zh"
    lookback_days: int = Field(default=5, gt=0)
    max_fetch: int = Field(default=3000, gt=0)
    max_candidates: int = Field(default=30, gt=0)
    max_papers: int = Field(default=15, gt=0)
    min_score: int = Field(default=6, ge=1, le=10)
    llm: LLMConfig = LLMConfig()
    site_title: str = "arXiv Radar"
    data_dir: Path = Path("data")
    site_dir: Path = Path("site")


def load_config(path: Path) -> Config:
    with path.open(encoding="utf-8") as f:
        return Config.model_validate(yaml.safe_load(f))
