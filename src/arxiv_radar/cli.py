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


class _ActionsAnnotations(logging.Handler):
    """Repeat errors as GitHub Actions annotations.

    Annotations show on a run's summary page, which anyone can read. The full log
    needs a sign-in, so without this a failed run gives no visible reason.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)

    def emit(self, record: logging.LogRecord) -> None:
        if os.environ.get("GITHUB_ACTIONS") != "true":
            return
        message = record.getMessage()
        for raw, escaped in (("%", "%25"), ("\r", "%0D"), ("\n", "%0A")):
            message = message.replace(raw, escaped)
        print(f"::error title=arXiv Radar::{message}", flush=True)


def _configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # The SDK logs every request at INFO, which buries the pipeline's own messages.
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    root = logging.getLogger()
    if not any(isinstance(handler, _ActionsAnnotations) for handler in root.handlers):
        root.addHandler(_ActionsAnnotations())


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

    _configure_logging()
    config = load_config(args.config)

    if args.command == "run":
        try:
            digest = run(config, _make_reviewer(config, args.no_llm))
        except (ArxivError, LLMError) as error:
            log.error("%s", error)
            return 1
        except Exception as error:
            # Anything unexpected still fails the run; this puts its cause in the log
            # and, on GitHub, on the run's summary page.
            log.exception("Unexpected %s: %s", type(error).__name__, error)
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
