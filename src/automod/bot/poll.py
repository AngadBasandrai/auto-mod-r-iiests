"""One polling pass: read new posts and mentions, answer what we can.

Designed to be run on a schedule (GitHub Actions cron) rather than as a
long-lived stream, so every run is independent and safe to repeat.

Safety rails, in the order they fire:
  1. DRY_RUN (default true) — logs the exact comment, posts nothing.
  2. max_post_age_minutes — never touch backlog. Stops a first-run spam disaster.
  3. seen.json + a live "did I already comment here?" check against Reddit.
  4. retrieval confidence gate — silence beats a wrong answer.
  5. per-run and per-hour reply caps.
"""

from __future__ import annotations

import argparse
import logging
import time

import praw

from .. import answer as answer_mod
from .. import config, lang
from ..index.store import Index
from . import state as state_mod
from .reddit_client import make_reddit

log = logging.getLogger(__name__)


def _age_minutes(created_utc: float) -> float:
    return (time.time() - created_utc) / 60.0


def _flair_matches(submission) -> bool:
    flair = (submission.link_flair_text or "").strip().lower()
    if not flair:
        return False
    triggers = {f.strip().lower() for f in config.get("bot.trigger_flairs", [])}
    return flair in triggers


def _submission_text(submission) -> str:
    body = (submission.selftext or "").strip()
    if body.lower() in {"[removed]", "[deleted]"}:
        body = ""
    return f"{submission.title}\n\n{body}".strip()


class Poller:
    def __init__(self, reddit: praw.Reddit, index: Index, *, dry_run: bool | None = None) -> None:
        self.reddit = reddit
        self.index = index
        self.state = state_mod.State()
        self.dry_run = config.settings.dry_run if dry_run is None else dry_run
        self.username = config.settings.reddit_username
        self.subreddit_name = config.get("subreddit", "iiests")
        self.posted = 0
        self.max_per_run = config.get("bot.max_replies_per_run", 3)
        self.max_per_hour = config.get("bot.max_replies_per_hour", 8)

    # -- capacity -----------------------------------------------------------
    def _has_capacity(self) -> bool:
        if self.posted >= self.max_per_run:
            log.info("Per-run reply cap reached (%d)", self.max_per_run)
            return False
        if self.state.replies_last_hour() >= self.max_per_hour:
            log.info("Per-hour reply cap reached (%d)", self.max_per_hour)
            return False
        return True

    # -- posting ------------------------------------------------------------
    def _reply(self, target, body: str, label: str) -> bool:
        if self.dry_run:
            log.info(
                "[DRY RUN] would reply to %s (%s):\n%s\n%s",
                label,
                target.id,
                "-" * 60,
                body,
            )
            self.posted += 1
            return True
        try:
            comment = target.reply(body)
        except praw.exceptions.RedditAPIException as exc:
            log.error("Reddit rejected the reply to %s: %s", target.id, exc)
            return False
        except Exception as exc:  # noqa: BLE001
            log.error("Failed to reply to %s: %s", target.id, exc)
            return False

        log.info("Replied to %s (%s) -> %s", label, target.id, getattr(comment, "id", "?"))
        self.posted += 1
        self.state.record_reply()
        return True

    # -- handlers -----------------------------------------------------------
    def handle_submission(self, submission, *, summoned: bool = False) -> None:
        question = _submission_text(submission)
        if len(question) < 15:
            return

        normalized = lang.normalize_query(question)
        result = answer_mod.generate(question, self.index, normalized=normalized)

        if not result.should_post:
            log.info(
                "Skipping %s (%s) — %s [top=%.2f, supporting=%d] %r",
                submission.id,
                submission.title[:50],
                result.reason,
                result.top_score,
                result.supporting,
                normalized.detection.lang,
            )
            # A human who summoned the bot deserves an answer either way.
            if summoned:
                self._reply(
                    submission,
                    self._not_found_body(normalized),
                    "summons (no answer)",
                )
            return

        if state_mod.already_replied(submission, self.username):
            log.info("Already replied in %s — skipping", submission.id)
            return

        body = answer_mod.render_comment(result)
        log.info(
            "Answering %s [top=%.2f, supporting=%d, lang=%s]",
            submission.id,
            result.top_score,
            result.supporting,
            normalized.detection.lang,
        )
        self._reply(submission, body, "submission")

    def handle_mention(self, comment) -> None:
        parent_question = ""
        try:
            submission = comment.submission
            parent_question = _submission_text(submission)
        except Exception:  # noqa: BLE001
            submission = None

        # The question is whatever the person wrote around the summons, falling
        # back to the post they summoned the bot under.
        own_text = (comment.body or "").replace(f"u/{self.username}", " ")
        own_text = own_text.replace(f"/u/{self.username}", " ").strip()
        question = own_text if len(own_text) > 15 else parent_question
        if len(question) < 15:
            return

        normalized = lang.normalize_query(question)
        result = answer_mod.generate(question, self.index, normalized=normalized)

        if result.should_post:
            body = answer_mod.render_comment(result)
        else:
            log.info("Summoned on %s but no confident answer (%s)", comment.id, result.reason)
            body = self._not_found_body(normalized)

        self._reply(comment, body, "mention")

    def _not_found_body(self, normalized: lang.NormalizedQuery) -> str:
        messages = {
            "hi": "मेरे पास इस सवाल का भरोसेमंद जवाब नहीं है — यह अभी FAQ में नहीं है। "
            "किसी सीनियर या मॉड से पूछ लीजिए।",
            "hinglish": "Iska reliable answer mere paas nahi hai — ye abhi FAQ mein nahi "
            "hai. Kisi senior ya mod se pooch lo.",
            "en": "I don't have a reliable answer for this one — it isn't in the FAQ yet. "
            "Worth asking a senior or a mod directly.",
        }
        footer = config.get("answer.footer", "") or ""
        return messages[normalized.detection.lang] + "\n" + footer.rstrip() + "\n"

    # -- passes -------------------------------------------------------------
    def poll_mentions(self) -> None:
        limit = config.get("bot.mentions_limit", 25)
        try:
            mentions = list(self.reddit.inbox.mentions(limit=limit))
        except Exception as exc:  # noqa: BLE001
            log.error("Could not read mentions: %s", exc)
            return

        for comment in mentions:
            if not self._has_capacity():
                return
            if self.state.is_seen("mentions", comment.id):
                continue
            subreddit = str(getattr(comment, "subreddit", "")).lower()
            if subreddit != self.subreddit_name.lower():
                self.state.mark_seen("mentions", comment.id)
                continue

            log.info("Handling mention %s", comment.id)
            self.handle_mention(comment)
            self.state.mark_seen("mentions", comment.id)
            if not self.dry_run:
                try:
                    comment.mark_read()
                except Exception:  # noqa: BLE001
                    pass

    def poll_new(self) -> None:
        limit = config.get("bot.new_posts_limit", 50)
        max_age = config.get("bot.max_post_age_minutes", 120)
        auto_unflaired = config.get("bot.auto_reply_unflaired", True)

        try:
            submissions = list(self.reddit.subreddit(self.subreddit_name).new(limit=limit))
        except Exception as exc:  # noqa: BLE001
            log.error("Could not read r/%s/new: %s", self.subreddit_name, exc)
            return

        for submission in submissions:
            if not self._has_capacity():
                return
            if self.state.is_seen("submissions", submission.id):
                continue

            age = _age_minutes(submission.created_utc)
            if age > max_age:
                # Older than our window: mark seen so we never backfill it later.
                self.state.mark_seen("submissions", submission.id)
                continue

            author = getattr(submission, "author", None)
            if author is not None and author.name.lower() == self.username.lower():
                self.state.mark_seen("submissions", submission.id)
                continue

            flaired = _flair_matches(submission)
            unflaired = not (submission.link_flair_text or "").strip()
            if not flaired and not (auto_unflaired and unflaired):
                self.state.mark_seen("submissions", submission.id)
                continue

            log.info(
                "Considering %s (%.0f min old, flair=%r): %s",
                submission.id,
                age,
                submission.link_flair_text,
                submission.title[:70],
            )
            self.handle_submission(submission)
            self.state.mark_seen("submissions", submission.id)

    def poll_feedback(self) -> None:
        """Honour `!badbot`: delete the offending comment and log it for repair."""
        triggers = [t.lower() for t in config.get("bot.removal_triggers", [])]
        if not triggers:
            return
        try:
            own_comments = list(self.reddit.user.me().comments.new(limit=25))
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not read own comments: %s", exc)
            return

        for comment in own_comments:
            try:
                comment.refresh()
                replies = list(comment.replies)
            except Exception:  # noqa: BLE001
                continue

            complaint = next(
                (r for r in replies if any(t in (r.body or "").lower() for t in triggers)),
                None,
            )
            # A negative score is the community saying the same thing.
            if complaint is None and comment.score > -3:
                continue

            reason = "!badbot" if complaint is not None else f"score {comment.score}"
            log.info("Removing own comment %s (%s)", comment.id, reason)
            self._log_feedback(comment, reason)
            if not self.dry_run:
                try:
                    comment.delete()
                except Exception as exc:  # noqa: BLE001
                    log.warning("Could not delete %s: %s", comment.id, exc)

    def _log_feedback(self, comment, reason: str) -> None:
        import json

        config.FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
        with config.FEEDBACK_PATH.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "comment_id": comment.id,
                        "permalink": f"https://www.reddit.com{comment.permalink}",
                        "reason": reason,
                        "score": comment.score,
                        "body": comment.body,
                        "ts": time.time(),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    def run(self) -> int:
        log.info(
            "Polling r/%s as u/%s (dry_run=%s, index=%d records)",
            self.subreddit_name,
            self.username,
            self.dry_run,
            len(self.index),
        )
        self.poll_feedback()
        self.poll_mentions()
        self.poll_new()
        self.state.save()
        log.info("Done. %d repl%s this run.", self.posted, "y" if self.posted == 1 else "ies")
        return self.posted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One polling pass over r/iiests.")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Actually post comments (otherwise DRY_RUN from .env applies).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Force dry run regardless of the environment.",
    )
    args = parser.parse_args(argv)

    config.setup_logging()
    config.ensure_dirs()

    dry_run: bool | None = None
    if args.dry_run:
        dry_run = True
    elif args.live:
        dry_run = False

    index = Index.load()
    reddit = make_reddit()
    Poller(reddit, index, dry_run=dry_run).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
