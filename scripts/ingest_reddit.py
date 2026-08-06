"""Pull the subreddit's own knowledge (wiki, pinned posts, top threads).

    python scripts/ingest_reddit.py

Writes data/corpus/reddit.jsonl. Read-only — needs only client id/secret.
"""

from __future__ import annotations

import _bootstrap  # noqa: F401
import logging

from automod import config
from automod.bot.reddit_client import make_readonly_reddit
from automod.ingest import reddit_faq

log = logging.getLogger("ingest_reddit")


def main() -> int:
    config.setup_logging()
    config.ensure_dirs()
    reddit = make_readonly_reddit()
    path = reddit_faq.run(reddit)
    log.info("Next: python scripts/build_corpus.py")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
