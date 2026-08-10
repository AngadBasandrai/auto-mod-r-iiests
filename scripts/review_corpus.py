"""Print the corpus in a form a human can actually review.

    python scripts/review_corpus.py > review.txt
    python scripts/review_corpus.py --numbers        # only rows asserting a figure
    python scripts/review_corpus.py --grep fee
    python scripts/review_corpus.py --topic hostel --source whatsapp

Rows are grouped by topic and sorted by question, so near-duplicate questions
land next to each other — which is how you spot the corpus contradicting itself.

Anything wrong goes into data/corpus/blocklist.txt. Editing qa.jsonl directly
does not survive, because build_corpus.py regenerates it from the source files
on every run.
"""

from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import re
from collections import defaultdict

from automod import config
from automod.curate.build_corpus import load_corpus

# A figure a student might act on. Every branch must reach an actual digit, and
# "rs" needs a word boundary in front of it — without one it matches the tail of
# "droppers." and drags in half the corpus.
FIGURE = re.compile(
    r"\brs\.?\s*\d[\d,.]*"          # Rs 27,000
    r"|₹\s*\d[\d,.]*"               # ₹27000
    r"|\b\d[\d,.]*\s*(?:k\b|lakhs?\b|crores?\b|%|kms?\b)"  # 27.7k, 5 lakh, 150km
    r"|\b\d[\d,.]*\s*(?:per\s+)?(?:semester|sem|year|month)\b",
    re.I,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grep", help="Only rows matching this regex (question or answer).")
    parser.add_argument("--topic", help="Only this topic.")
    parser.add_argument("--source", help="Only this source, e.g. whatsapp or student_wiki.")
    parser.add_argument(
        "--numbers",
        action="store_true",
        help="Only rows whose answer asserts a figure — fees, cutoffs, distances. "
        "These are the ones where being wrong actually costs somebody something.",
    )
    parser.add_argument("--min-confidence", type=float, default=0.0)
    args = parser.parse_args()

    rows = load_corpus()
    total = len(rows)

    if args.topic:
        rows = [r for r in rows if r.get("topic", "").lower() == args.topic.lower()]
    if args.source:
        rows = [r for r in rows if r.get("source", "") == args.source]
    if args.min_confidence:
        rows = [r for r in rows if float(r.get("confidence", 0)) >= args.min_confidence]
    if args.numbers:
        rows = [r for r in rows if FIGURE.search(r.get("answer", ""))]
    if args.grep:
        pattern = re.compile(args.grep, re.I)
        rows = [
            r for r in rows
            if pattern.search(r.get("question", "")) or pattern.search(r.get("answer", ""))
        ]

    by_topic: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_topic[row.get("topic", "?")].append(row)

    print(f"{len(rows)} of {total} rows\n")

    for topic in sorted(by_topic):
        group = sorted(by_topic[topic], key=lambda r: r.get("question", "").lower())
        print(f"\n{'=' * 76}\n{topic.upper()}  ({len(group)})\n{'=' * 76}")
        for row in group:
            confidence = float(row.get("confidence", 0))
            print(f"\n[{confidence:.2f}] [{row.get('source', '?')}] {row.get('question', '')}")
            print(f"    {row.get('answer', '')}")
            original = row.get("question_original", "")
            if original and original != row.get("question", ""):
                print(f"    asked as: {original}")
            if row.get("ref"):
                print(f"    ref: {row['ref']}")

    print(f"\n\nWrong rows -> {config.CORPUS_DIR / 'blocklist.txt'}, then:")
    print("  python scripts/build_corpus.py --check-blocklist")
    print("  python scripts/build_corpus.py")
    print("  python scripts/build_index.py")
    print("  python scripts/export_corpus_json.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
