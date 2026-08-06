"""Build the hybrid search index from data/corpus/qa.jsonl.

    python scripts/build_index.py
"""

from __future__ import annotations

import _bootstrap  # noqa: F401
import logging

from automod import config
from automod.index import build

log = logging.getLogger("build_index")


def main() -> int:
    config.setup_logging()
    config.ensure_dirs()
    index = build.run()
    log.info("Index ready: %d records. Next: python scripts/ask.py \"your question\"", len(index))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
