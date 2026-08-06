"""Run-to-run state: what has already been handled.

The committed seen.json is a fast path, not the source of truth. GitHub Actions
runs are ephemeral and a push can fail, so before commenting the bot always asks
Reddit itself whether it already replied in that thread. That check is what makes
double-posting impossible; seen.json just saves the API calls.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from .. import config

log = logging.getLogger(__name__)

MAX_SEEN = 2000


class State:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config.SEEN_PATH
        self.seen_submissions: list[str] = []
        self.seen_mentions: list[str] = []
        self.replies: list[float] = []  # unix timestamps of posted replies
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Could not read %s (%s) — starting fresh", self.path, exc)
            return
        self.seen_submissions = list(data.get("seen_submissions", []))
        self.seen_mentions = list(data.get("seen_mentions", []))
        self.replies = list(data.get("replies", []))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "seen_submissions": self.seen_submissions[-MAX_SEEN:],
            "seen_mentions": self.seen_mentions[-MAX_SEEN:],
            "replies": self.recent_replies(hours=24),
            "updated_at": time.time(),
        }
        self.path.write_text(json.dumps(payload, indent=1), encoding="utf-8")

    # -- submissions / mentions --------------------------------------------
    def is_seen(self, kind: str, item_id: str) -> bool:
        return item_id in getattr(self, f"seen_{kind}")

    def mark_seen(self, kind: str, item_id: str) -> None:
        bucket = getattr(self, f"seen_{kind}")
        if item_id not in bucket:
            bucket.append(item_id)

    # -- rate limiting ------------------------------------------------------
    def recent_replies(self, hours: float = 1.0) -> list[float]:
        cutoff = time.time() - hours * 3600
        return [t for t in self.replies if t >= cutoff]

    def replies_last_hour(self) -> int:
        return len(self.recent_replies(hours=1.0))

    def record_reply(self) -> None:
        self.replies.append(time.time())


def already_replied(submission, username: str) -> bool:
    """Authoritative check: does the bot already have a comment in this thread?"""
    try:
        submission.comments.replace_more(limit=0)
        for comment in submission.comments.list():
            author = getattr(comment, "author", None)
            if author is not None and author.name.lower() == username.lower():
                return True
    except Exception as exc:  # noqa: BLE001 - fail closed
        log.warning("Could not verify existing replies on %s: %s", submission.id, exc)
        return True
    return False
