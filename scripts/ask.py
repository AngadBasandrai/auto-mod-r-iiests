"""Ask the bot a question from the terminal — the fastest way to judge quality.

    python scripts/ask.py "hostel fees kitni hai"
    python scripts/ask.py "What is the hostel fee?" --show-hits
    python scripts/ask.py                              # interactive
"""

from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import logging

from automod import answer as answer_mod
from automod import config, lang
from automod.index.store import Index

log = logging.getLogger("ask")


def ask_once(question: str, index: Index, show_hits: bool) -> None:
    normalized = lang.normalize_query(question)
    detection = normalized.detection
    print(f"\ndetected  : {detection.lang} ({detection.script})"
          f"{' via ' + ', '.join(detection.marker_hits[:5]) if detection.marker_hits else ''}")
    print(f"english   : {normalized.english}")
    print(f"keywords  : {', '.join(normalized.keywords)}")

    result = answer_mod.generate(question, index, normalized=normalized)

    if show_hits:
        print("\nretrieved :")
        for hit in result.hits:
            print(f"  [{hit.score:.2f}] ({hit.record.source}) {hit.record.question[:80]}")

    print(f"\nconfidence: top={result.top_score:.2f} supporting={result.supporting} "
          f"-> {'ANSWER' if result.should_post else 'SILENT'} ({result.reason})")

    if result.should_post:
        print("\n" + "-" * 70)
        print(answer_mod.render_comment(result))
        print("-" * 70)
    else:
        print("\n(the bot would stay silent on an auto-triggered post)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="*", help="The question. Omit for interactive mode.")
    parser.add_argument("--show-hits", action="store_true", help="Print the retrieved records.")
    args = parser.parse_args()

    config.setup_logging()
    index = Index.load()
    log.info("Loaded index with %d records", len(index))

    if args.question:
        ask_once(" ".join(args.question), index, args.show_hits)
        return 0

    print("Interactive mode. Blank line or Ctrl-C to quit.")
    while True:
        try:
            question = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question:
            break
        ask_once(question, index, args.show_hits)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
