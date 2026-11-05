"""Files under data/: one JSON digest per day, plus the ids already processed."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from .models import Digest

SEEN_RETENTION_DAYS = 30  # must stay well above lookback_days


def _digest_path(data_dir: Path, date: dt.date) -> Path:
    return data_dir / "digests" / f"{date.isoformat()}.json"


def load_seen(data_dir: Path) -> dict[str, str]:
    path = data_dir / "seen.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_seen(data_dir: Path, seen: dict[str, str], today: dt.date) -> None:
    cutoff = (today - dt.timedelta(days=SEEN_RETENTION_DAYS)).isoformat()
    kept = {paper_id: date for paper_id, date in seen.items() if date >= cutoff}
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "seen.json").write_text(
        json.dumps(kept, indent=0, sort_keys=True) + "\n", encoding="utf-8"
    )


def load_digest(data_dir: Path, date: dt.date) -> Digest | None:
    path = _digest_path(data_dir, date)
    if not path.exists():
        return None
    return Digest.model_validate_json(path.read_text(encoding="utf-8"))


def save_digest(data_dir: Path, digest: Digest) -> None:
    path = _digest_path(data_dir, digest.date)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(digest.model_dump_json(indent=2) + "\n", encoding="utf-8")


def load_all_digests(data_dir: Path) -> list[Digest]:
    """Return every saved digest, newest first."""
    paths = sorted((data_dir / "digests").glob("*.json"), reverse=True)
    return [Digest.model_validate_json(path.read_text(encoding="utf-8")) for path in paths]
