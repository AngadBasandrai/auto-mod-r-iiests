"""Parse the WhatsApp export and distil it into Q&A pairs.

    python scripts/ingest_whatsapp.py --limit 20 --dry-run   # cheap preview
    python scripts/ingest_whatsapp.py                        # full run

Reads data/raw/whatsapp/*.txt (gitignored). Writes data/corpus/whatsapp.jsonl.
Extraction results are cached by window hash, so re-running after a prompt tweak
only pays for what changed.
"""

from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import json
import logging
import random

from automod import config
from automod.curate import extract as extract_mod
from automod.curate.sessionize import sessionize
from automod.ingest import whatsapp

log = logging.getLogger("ingest_whatsapp")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="Only process N windows (sampled evenly).")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print extracted pairs instead of writing the corpus file.",
    )
    parser.add_argument("--workers", type=int, help="Override curate.extract_workers.")
    parser.add_argument("--seed", type=int, default=0, help="Sampling seed for --limit.")
    args = parser.parse_args()

    config.setup_logging()
    config.ensure_dirs()

    messages = whatsapp.load_all(config.WHATSAPP_DIR)
    ing = config.get("ingest.whatsapp", {})
    windows = sessionize(
        messages,
        gap_minutes=ing.get("session_gap_minutes", 45),
        max_messages=ing.get("session_max_messages", 25),
        overlap=ing.get("session_overlap", 3),
    )
    log.info("%d messages -> %d conversation windows", len(messages), len(windows))

    if args.limit and args.limit < len(windows):
        # Sample across the whole history rather than taking the first N, so a
        # preview reflects how the chat actually looks over time.
        rng = random.Random(args.seed)
        windows = sorted(rng.sample(windows, args.limit), key=lambda w: w.start)
        log.info("Sampled %d windows for this run", len(windows))

    pairs = extract_mod.extract_all(windows, workers=args.workers)

    kept = sum(1 for p in pairs if p["confidence"] >= config.get("curate.min_confidence", 0.6))
    log.info(
        "%d pairs extracted from %d windows (%d above the confidence floor); "
        "%.1f%% of windows yielded nothing",
        len(pairs),
        len(windows),
        kept,
        100.0 * (1 - len({p["window"] for p in pairs}) / max(1, len(windows))),
    )

    if args.dry_run:
        for pair in pairs[:40]:
            print(f"\n[{pair['topic']} | conf {pair['confidence']:.2f} | {pair['ref']}]")
            print(f"  Q  {pair['question']}")
            print(f"  Q* {pair['question_original']}")
            print(f"  A  {pair['answer']}")
        print(f"\n({len(pairs)} pairs total, showing up to 40)")
        return 0

    out = config.WHATSAPP_RAW_PATH
    with out.open("w", encoding="utf-8") as fh:
        for pair in pairs:
            fh.write(json.dumps(pair, ensure_ascii=False) + "\n")
    log.info("Wrote %d pairs -> %s", len(pairs), out)
    log.info("Next: python scripts/build_corpus.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
