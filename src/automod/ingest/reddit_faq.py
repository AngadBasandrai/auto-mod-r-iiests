"""Pull existing knowledge out of r/iiests itself.

Three sources, in decreasing order of trust:
  1. wiki pages (mod-curated)
  2. pinned / stickied submissions (megathreads, FAQ posts)
  3. historical submissions with a well-upvoted answer in the comments

Everything is emitted as raw {question, answer} rows into data/corpus/reddit.jsonl.
Curation (PII scrub, dedupe) happens later in the same pipeline as WhatsApp so
both sources get identical treatment.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable

import praw
import prawcore

from .. import config

log = logging.getLogger(__name__)

REMOVED = {"[removed]", "[deleted]", ""}


def _is_usable_comment(comment: Any, min_score: int, min_chars: int) -> bool:
    body = (getattr(comment, "body", "") or "").strip()
    if body.lower() in REMOVED:
        return False
    if getattr(comment, "stickied", False):
        return False
    if comment.score < min_score:
        return False
    if len(body) < min_chars:
        return False
    if getattr(comment, "author", None) is None:
        return False
    return True


def fetch_wiki(reddit: praw.Reddit, subreddit_name: str, pages: Iterable[str]) -> list[dict]:
    rows: list[dict] = []
    subreddit = reddit.subreddit(subreddit_name)
    for page in pages:
        try:
            wiki = subreddit.wiki[page]
            content = (wiki.content_md or "").strip()
        except (prawcore.exceptions.NotFound, prawcore.exceptions.Forbidden) as exc:
            log.info("Wiki page %r unavailable (%s)", page, type(exc).__name__)
            continue
        except Exception as exc:  # noqa: BLE001
            log.warning("Wiki page %r failed: %s", page, exc)
            continue
        if len(content) < 100:
            continue
        rows.append(
            {
                "source": "reddit_wiki",
                "ref": f"https://www.reddit.com/r/{subreddit_name}/wiki/{page}",
                "title": f"r/{subreddit_name} wiki: {page}",
                "text": content,
            }
        )
        log.info("Wiki page %r: %d chars", page, len(content))
    return rows


def _submission_rows(
    submission: Any,
    *,
    subreddit_name: str,
    max_comments: int,
    min_comment_score: int,
    min_answer_chars: int,
    tag: str,
) -> dict | None:
    selftext = (submission.selftext or "").strip()
    if selftext.lower() in REMOVED:
        selftext = ""
    question = f"{submission.title}\n\n{selftext}".strip()
    if not question:
        return None

    try:
        submission.comments.replace_more(limit=0)
        comments = sorted(
            submission.comments, key=lambda c: getattr(c, "score", 0), reverse=True
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not load comments for %s: %s", submission.id, exc)
        return None

    answers = [
        c.body.strip()
        for c in comments
        if _is_usable_comment(c, min_comment_score, min_answer_chars)
    ][:max_comments]

    if not answers:
        return None

    return {
        "source": tag,
        "ref": f"https://www.reddit.com{submission.permalink}",
        "title": submission.title,
        "question": question,
        "answers": answers,
        "score": submission.score,
        "flair": submission.link_flair_text,
        "created_utc": submission.created_utc,
    }


def fetch_submissions(reddit: praw.Reddit, subreddit_name: str) -> list[dict]:
    ing = config.get("ingest.reddit", {})
    subreddit = reddit.subreddit(subreddit_name)
    rows: list[dict] = []
    seen: set[str] = set()

    common = {
        "subreddit_name": subreddit_name,
        "max_comments": ing.get("max_comments_per_post", 3),
        "min_comment_score": ing.get("min_comment_score", 2),
        "min_answer_chars": ing.get("min_answer_chars", 80),
    }

    # 1. Pinned posts -- usually the megathreads. Reddit allows at most two.
    for index in (1, 2):
        try:
            submission = subreddit.sticky(number=index)
        except Exception:  # noqa: BLE001
            continue
        if submission.id in seen:
            continue
        seen.add(submission.id)
        row = _submission_rows(submission, tag="reddit_pinned", **common)
        if row:
            rows.append(row)
        elif (submission.selftext or "").strip():
            # A pinned FAQ post is valuable even with no comments.
            rows.append(
                {
                    "source": "reddit_pinned",
                    "ref": f"https://www.reddit.com{submission.permalink}",
                    "title": submission.title,
                    "text": submission.selftext.strip(),
                }
            )

    # 2. Historical top posts with a real answer underneath.
    min_score = ing.get("min_score", 3)
    listing = subreddit.top(
        time_filter=ing.get("top_time_filter", "all"),
        limit=ing.get("top_limit", 300),
    )
    for submission in listing:
        if submission.id in seen or submission.score < min_score:
            continue
        seen.add(submission.id)
        row = _submission_rows(submission, tag="reddit_thread", **common)
        if row:
            rows.append(row)

    log.info("Collected %d submission rows from r/%s", len(rows), subreddit_name)
    return rows


def run(reddit: praw.Reddit, out_path: Path | None = None) -> Path:
    subreddit_name = config.get("subreddit", "iiests")
    out_path = out_path or config.REDDIT_RAW_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows = fetch_wiki(
        reddit, subreddit_name, config.get("ingest.reddit.wiki_pages", ["index", "faq"])
    )
    rows += fetch_submissions(reddit, subreddit_name)

    with out_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    log.info("Wrote %d rows -> %s", len(rows), out_path)
    return out_path
