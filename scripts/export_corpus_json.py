"""Export the built corpus into the Devvit app bundle.

    python scripts/export_corpus_json.py

Reads data/corpus/qa.jsonl and writes devvit/src/server/corpus.generated.json.

The Devvit server entry is one self-contained JavaScript file with no
filesystem, so the corpus cannot be loaded at runtime — esbuild inlines this
file into the bundle instead. That makes the export a build step: rerun it after
every `build_corpus.py`, or the deployed bot answers from a stale knowledge base.

Only the fields the TypeScript retriever reads are written out, which keeps the
bundle roughly a third smaller than the source JSONL.
"""

from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import json
import logging
from collections import Counter
from pathlib import Path

from automod import config
from automod.curate.build_corpus import load_corpus
from automod.curate.scrub import find_leaks

log = logging.getLogger("export_corpus_json")

OUT_PATH = config.ROOT / "devvit" / "src" / "server" / "corpus.generated.json"

FIELDS = ("question", "question_original", "answer", "topic", "source", "ref", "confidence")

# The bundle is uploaded to Reddit and served on every trigger. Well past
# anything this corpus should reach, but a runaway ingest should fail loudly
# rather than produce an app that will not deploy.
MAX_BYTES = 12 * 1024 * 1024


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    parser.add_argument(
        "--pretty", action="store_true", help="Indent the output. Larger, but diffable."
    )
    args = parser.parse_args()

    config.setup_logging()
    try:
        rows = load_corpus()
    except FileNotFoundError as exc:
        log.error("%s", exc)
        return 1
    if not rows:
        log.error("Corpus is empty. Run scripts/build_corpus.py first.")
        return 1

    # The same audit build_corpus.py --check runs. This file is committed and
    # then shipped inside a deployed app, so it gets checked on the way out too.
    leaks: list[str] = []
    for i, row in enumerate(rows):
        blob = "\n".join(str(row.get(f, "")) for f in ("question", "question_original", "answer"))
        leaks.extend(f"row {i}: {leak}" for leak in find_leaks(blob))
    if leaks:
        log.error("Refusing to export: %d possible PII leaks", len(leaks))
        for leak in leaks[:25]:
            log.error("  %s", leak)
        log.error("Fix data/corpus/qa.jsonl, then re-run.")
        return 1

    slim = [{f: row.get(f, "") for f in FIELDS} for row in rows]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(slim, ensure_ascii=False, indent=2 if args.pretty else None),
        encoding="utf-8",
    )

    size = args.out.stat().st_size
    if size > MAX_BYTES:
        log.error("%s is %.1f MB, over the %d MB ceiling", args.out, size / 1e6, MAX_BYTES // 2**20)
        return 1

    by_source = Counter(row.get("source", "?") for row in rows)
    log.info("Wrote %d rows (%.2f MB) -> %s", len(slim), size / 1e6, args.out)
    log.info("Sources: %s", dict(by_source))
    log.info("Next: cd devvit && npm run build")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
