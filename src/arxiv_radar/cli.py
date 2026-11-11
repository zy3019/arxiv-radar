"""Command line entry point."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .config import Config, load_config
from .fetch import ArxivError
from .llm import LLMError, Reviewer, make_reviewer
from .pipeline import run
from .render import build_site

log = logging.getLogger("arxiv_radar")


def _make_reviewer(config: Config, no_llm: bool) -> Reviewer | None:
    if no_llm:
        return None
    api_key = os.environ.get(config.llm.api_key_env)
    if not api_key:
        log.warning(
            "%s is not set: ranking by keyword only, with no summaries", config.llm.api_key_env
        )
        return None
    return make_reviewer(config.llm, config.interests, config.language, api_key)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arxiv-radar", description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="fetch today's papers and rebuild the site")
    run_parser.add_argument("--no-llm", action="store_true", help="rank by keyword only")
    commands.add_parser("build", help="rebuild the site from saved digests")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # The SDK logs every request at INFO, which buries the pipeline's own messages.
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    config = load_config(args.config)

    if args.command == "run":
        try:
            digest = run(config, _make_reviewer(config, args.no_llm))
        except ArxivError as error:
            log.error("%s", error)
            return 1
        except LLMError as error:
            log.error("%s", error)
            return 1
        if digest is None:
            log.info("Nothing new on arXiv since the last run")
        else:
            log.info("Digest %s: %d papers", digest.date, len(digest.entries))

    pages = build_site(config, os.environ.get("RADAR_SITE_URL", ""))
    log.info("Built %d daily pages in %s", pages, config.site_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
