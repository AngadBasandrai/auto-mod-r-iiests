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


def check_blocklist() -> int:
    """Dry-run the blocklist against the current corpus.

    Worth doing before every commit to blocklist.txt: a pattern meant for one
    bad fee row can quietly take out a dozen good ones, and you would only find
    out when the bot went quiet on a whole topic.
    """
    patterns = build_corpus.load_blocklist()
    if not patterns:
        print(f"No patterns in {build_corpus.BLOCKLIST_PATH}")
        return 0

    rows = build_corpus.load_corpus()
    print(f"{len(patterns)} patterns against {len(rows)} rows in the built corpus\n")

    total = 0
    for pattern in patterns:
        matched = [
            r for r in rows
            if pattern.search(f"{r.get('question', '')} {r.get('answer', '')}")
        ]
        total += len(matched)
        marker = "  " if len(matched) == 1 else "! " if len(matched) > 1 else "? "
        print(f"{marker}{pattern.pattern}  -> {len(matched)} row(s)")
        for row in matched[:5]:
            print(f"      {row.get('question', '')[:70]}")
            print(f"        {row.get('answer', '')[:80]}")
        if len(matched) > 5:
            print(f"      ... and {len(matched) - 5} more")

    print(f"\n{total} of {len(rows)} rows would be dropped.")
    print("'!' means a pattern matched more than one row — check that is intended.")
    print("'?' means it matched nothing; the row may already be gone, or the pattern is wrong.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Audit the existing corpus instead of rebuilding.")
    parser.add_argument(
        "--check-blocklist",
        action="store_true",
        help="Show which corpus rows data/corpus/blocklist.txt would drop.",
    )
    args = parser.parse_args()

    config.setup_logging()
    config.ensure_dirs()

    if args.check:
        return audit()
    if args.check_blocklist:
        return check_blocklist()

    whatsapp_pairs = load_jsonl(config.WHATSAPP_RAW_PATH)
    log.info("Loaded %d WhatsApp pairs", len(whatsapp_pairs))
    reddit_pairs = build_corpus.pairs_from_reddit()
    log.info("Loaded %d Reddit pairs", len(reddit_pairs))
    wiki_pairs = build_corpus.pairs_from_wiki()
    log.info("Loaded %d student-wiki pairs", len(wiki_pairs))

    if not whatsapp_pairs and not reddit_pairs and not wiki_pairs:
        log.error(
            "Nothing to build. Run scripts/ingest_whatsapp.py, scripts/ingest_reddit.py "
            "and/or scripts/ingest_wiki.py first."
        )
        return 1

    build_corpus.build(whatsapp_pairs, reddit_pairs, wiki_pairs)
    log.info("Next: python scripts/build_corpus.py --check, then python scripts/build_index.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
