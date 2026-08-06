"""Merge, filter, scrub and dedupe every source into data/corpus/qa.jsonl.

    python scripts/build_corpus.py
    python scripts/build_corpus.py --check    # audit the result for PII leaks

This is the file that gets committed to a public repo, so it runs the scrubber
again on the way out and refuses to be careless about it.
"""

from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import json
import logging
from collections import Counter

from automod import config
from automod.curate import build_corpus
from automod.curate.scrub import find_leaks

log = logging.getLogger("build_corpus")


def load_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def audit() -> int:
    rows = build_corpus.load_corpus()
    leaks: list[tuple[int, str]] = []
    for i, row in enumerate(rows):
        blob = f"{row.get('question', '')}\n{row.get('question_original', '')}\n{row.get('answer', '')}"
        for leak in find_leaks(blob):
            leaks.append((i, leak))

    topics = Counter(r.get("topic", "?") for r in rows)
    sources = Counter(r.get("source", "?") for r in rows)
    print(f"rows      : {len(rows)}")
    print(f"sources   : {dict(sources)}")
    print(f"topics    : {dict(topics.most_common())}")
    print(f"avg conf  : {sum(float(r.get('confidence', 0)) for r in rows) / max(1, len(rows)):.2f}")

    if leaks:
        print(f"\nPOSSIBLE PII LEAKS: {len(leaks)}")
        for i, leak in leaks[:25]:
            print(f"  row {i}: {leak}")
        return 1
    print("\nNo PII patterns detected. Safe to commit.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Audit the existing corpus instead of rebuilding.")
    args = parser.parse_args()

    config.setup_logging()
    config.ensure_dirs()

    if args.check:
        return audit()

    whatsapp_pairs = load_jsonl(config.WHATSAPP_RAW_PATH)
    log.info("Loaded %d WhatsApp pairs", len(whatsapp_pairs))
    reddit_pairs = build_corpus.pairs_from_reddit()
    log.info("Loaded %d Reddit pairs", len(reddit_pairs))

    if not whatsapp_pairs and not reddit_pairs:
        log.error("Nothing to build. Run scripts/ingest_whatsapp.py and/or scripts/ingest_reddit.py first.")
        return 1

    build_corpus.build(whatsapp_pairs, reddit_pairs)
    log.info("Next: python scripts/build_corpus.py --check, then python scripts/build_index.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
