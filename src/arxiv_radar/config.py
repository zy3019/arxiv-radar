"""Load and validate config.yaml. Unknown keys are rejected so typos fail loudly."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = "claude-opus-5-5"
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    max_tokens: int = Field(default=8000, gt=0)
    concurrency: int = Field(default=4, gt=0)
    refusal_fallback: bool = True


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
