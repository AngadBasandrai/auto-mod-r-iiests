"""Crawl the student-run IIEST wiki (iiest-town.github.io).

    python scripts/ingest_wiki.py --dry-run     # print what it found, write nothing
    python scripts/ingest_wiki.py               # full crawl

Writes data/corpus/wiki.jsonl. No API keys needed — this step is a plain HTTP
crawl; the extraction model only runs later, in build_corpus.
"""

from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import logging

from automod import config
from automod.ingest import wiki_site

log = logging.getLogger("ingest_wiki")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="Only crawl the first N pages.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the sections found instead of writing the corpus file.",
    )
    args = parser.parse_args()

    config.setup_logging()
    config.ensure_dirs()

    if args.dry_run:
        cfg = config.get("ingest.wiki", {}) or {}
        base_url = cfg.get("base_url", "https://iiest-town.github.io/")
        urls = wiki_site.discover_urls(base_url, cfg.get("skip_paths", []))
        if args.limit:
            urls = urls[: args.limit]
        total = 0
        for url in urls:
            try:
                rows = wiki_site.rows_from_page(
                    url,
                    wiki_site.fetch(url),
                    min_section_chars=cfg.get("min_section_chars", 20),
                    skip_headings=cfg.get("skip_headings", []),
                )
            except Exception as exc:  # noqa: BLE001
                print(f"\n## {url}\n  FAILED: {exc}")
                continue
            total += len(rows)
            print(f"\n## {url}  ({len(rows)} sections)")
            for row in rows:
                if "answers" in row:
                    print(f"  [Q&A] {row['question']}")
                    print(f"        {row['answers'][0][:160]}")
                else:
                    print(f"  [doc] {row['text'].splitlines()[0]}")
                    print(f"        {row['text'][:160].replace(chr(10), ' ')}")
        print(f"\n{total} sections across {len(urls)} pages. Nothing written.")
        return 0

    rows = wiki_site.run(limit=args.limit)
    if not rows:
        log.error("Nothing collected. Is the site reachable?")
        return 1
    log.info("Next: python scripts/build_corpus.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
