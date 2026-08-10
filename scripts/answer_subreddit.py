"""Answer real r/iiests posts in your terminal. Never posts anything.

    python scripts/answer_subreddit.py                    # 25 newest posts
    python scripts/answer_subreddit.py --sort top --limit 50
    python scripts/answer_subreddit.py --show-hits        # show what was retrieved
    python scripts/answer_subreddit.py --out replay.txt

This is the honest dress rehearsal: the same retrieval, the same confidence gate
and the same generation the bot uses, against the questions people actually ask,
with the posting step removed. Read the output and you know what the bot would
have said all week.

READING THE SUBREDDIT WITHOUT CREDENTIALS
Reddit stopped issuing Data API keys in November 2025, so there is no OAuth
session to use. The public Atom feed still works and needs nothing:

    https://www.reddit.com/r/iiests/new/.rss

It carries the title, body, author and permalink — everything the bot reads off
a post except flair and score. It returns at most ~25 entries, so --limit above
that silently gets fewer; use --sort to reach different posts. If Reddit ever
issues you credentials, --use-api switches to PRAW and lifts both limits.

WHAT IS NOT SIMULATED
Flair gating and the post-age cutoff, because the feed carries no flair and the
point here is to replay a backlog. Duplicate suppression and the reply caps are
skipped too — they are about not repeating yourself, not about answer quality.
Everything that decides *whether the answer is any good* runs exactly as it does
in production.
"""

from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import html
import json
import logging
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

from automod import answer as answer_mod
from automod import config, lang
from automod.index.store import Index
from automod.retrieve import confidence

log = logging.getLogger("answer_subreddit")

# Reddit throttles hard on unfamiliar agents. This one is honest about what it
# is, which is what their guidance asks for.
USER_AGENT = "python:auto-mod-r-iiests:v0.1.0 (by /u/AngadBasandrai) local replay"

TAG = re.compile(r"<[^>]+>")
SUBMITTED_BY = re.compile(r"submitted by\s*/u/\S+.*$", re.I | re.S)


@dataclass
class Post:
    id: str
    title: str
    body: str
    author: str
    url: str
    created: datetime | None

    @property
    def question(self) -> str:
        return f"{self.title}\n\n{self.body}".strip()

    def age(self) -> str:
        if not self.created:
            return "?"
        hours = (datetime.now(timezone.utc) - self.created).total_seconds() / 3600
        if hours < 48:
            return f"{hours:.0f}h ago"
        return f"{hours / 24:.0f}d ago"


def _text(html_fragment: str) -> str:
    """Reddit's feed carries the post body as escaped HTML."""
    text = html.unescape(html_fragment or "")
    text = re.sub(r"<br\s*/?>|</p>", "\n", text, flags=re.I)
    text = TAG.sub("", text)
    text = html.unescape(text)
    # Every entry ends with a "submitted by /u/x [link] [comments]" footer.
    text = SUBMITTED_BY.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def fetch_rss(subreddit: str, sort: str, limit: int) -> list[Post]:
    """Posts from the public Atom feed. No credentials, no OAuth."""
    url = f"https://www.reddit.com/r/{subreddit}/{sort}/.rss?limit={min(limit, 100)}"
    if sort == "top":
        url += "&t=all"

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    raw = ""
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8", "replace")
            break
        except Exception as exc:  # noqa: BLE001 - one message covers every failure
            code = getattr(exc, "code", None)
            retryable = code in (429, 503) or code is None
            if retryable and attempt < 3:
                wait = 15 * attempt
                log.warning("Reddit returned %s; waiting %ds before retry", code or exc, wait)
                time.sleep(wait)
                continue
            raise SystemExit(
                f"Could not read r/{subreddit}: {exc}\n"
                "A 403, or a 429 that does not clear, means Reddit is throttling this IP. "
                "Wait a few minutes and retry, or use --file to replay questions from a "
                "text file instead."
            ) from exc

    posts: list[Post] = []
    for entry in re.findall(r"<entry>(.*?)</entry>", raw, re.S):

        def field(tag: str) -> str:
            match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", entry, re.S)
            return html.unescape(match.group(1)).strip() if match else ""

        link = re.search(r'<link[^>]*href="([^"]+)"', entry)
        content = re.search(r'<content[^>]*>(.*?)</content>', entry, re.S)
        created = None
        stamp = field("updated") or field("published")
        if stamp:
            try:
                created = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except ValueError:
                pass

        permalink = link.group(1) if link else ""
        posts.append(
            Post(
                id=field("id") or permalink or "?",
                title=_text(field("title")),
                body=_text(content.group(1) if content else ""),
                author=field("name") or "?",
                url=permalink,
                created=created,
            )
        )

    return posts[:limit]


def fetch_api(subreddit: str, sort: str, limit: int) -> list[Post]:
    """PRAW path, if Reddit ever issues credentials. Lifts the ~25 feed cap."""
    from automod.bot.reddit_client import make_readonly_reddit

    reddit = make_readonly_reddit()
    listing = getattr(reddit.subreddit(subreddit), sort)
    submissions = listing(time_filter="all", limit=limit) if sort == "top" else listing(limit=limit)

    return [
        Post(
            id=s.id,
            title=s.title,
            body=(s.selftext or "").strip(),
            author=str(s.author) if s.author else "[deleted]",
            url=f"https://www.reddit.com{s.permalink}",
            created=datetime.fromtimestamp(s.created_utc, tz=timezone.utc),
        )
        for s in submissions
    ]


def fetch_file(path: str) -> list[Post]:
    """One question per line, or a JSON list of {title, body}."""
    raw = open(path, encoding="utf-8").read().strip()
    if raw.startswith("["):
        return [
            Post(str(i), row.get("title", ""), row.get("body", ""), "-", "", None)
            for i, row in enumerate(json.loads(raw))
        ]
    return [
        Post(str(i), line.strip(), "", "-", "", None)
        for i, line in enumerate(raw.splitlines())
        if line.strip()
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subreddit", default=None, help="Defaults to config.yaml.")
    parser.add_argument("--sort", default="new", choices=["new", "hot", "top", "rising"])
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--show-hits", action="store_true", help="Print retrieved records.")
    parser.add_argument("--min-confidence", type=float, help="Override answer.min_confidence.")
    parser.add_argument("--use-api", action="store_true", help="Use PRAW instead of the feed.")
    parser.add_argument("--file", help="Replay questions from a file instead of Reddit.")
    parser.add_argument("--out", help="Also write the transcript to this file.")
    parser.add_argument(
        "--only-answers",
        action="store_true",
        help="Skip posts the bot would stay silent on.",
    )
    args = parser.parse_args()

    config.setup_logging()
    subreddit = args.subreddit or config.get("subreddit", "iiests")

    if args.min_confidence is not None:
        config.cfg()["answer"]["min_confidence"] = args.min_confidence
        log.info("Overriding answer.min_confidence -> %.2f", args.min_confidence)

    index = Index.load()
    log.info("Loaded index with %d records", len(index))

    if args.file:
        posts = fetch_file(args.file)
    elif args.use_api:
        posts = fetch_api(subreddit, args.sort, args.limit)
    else:
        posts = fetch_rss(subreddit, args.sort, args.limit)

    if not posts:
        log.error("No posts found.")
        return 1

    log.info(
        "Answering %d posts from r/%s (%s). Nothing will be posted.",
        len(posts),
        subreddit,
        args.sort,
    )
    log.info(
        "The free Groq tier paces this at roughly 2 posts/minute, so expect ~%d minutes.",
        max(1, round(len(posts) / 2)),
    )

    out = open(args.out, "w", encoding="utf-8") if args.out else None

    def emit(line: str = "") -> None:
        print(line)
        if out:
            out.write(line + "\n")
            out.flush()

    outcomes: dict[str, int] = {}
    answered = 0

    for number, post in enumerate(posts, 1):
        if not post.question:
            continue

        normalized = lang.normalize_query(post.question)
        result = answer_mod.generate(post.question, index, normalized=normalized)
        top, supporting = confidence(result.hits)

        reason = result.reason if not result.should_post else "answered"
        outcomes[reason] = outcomes.get(reason, 0) + 1
        if result.should_post:
            answered += 1
        elif args.only_answers:
            continue

        emit()
        emit("=" * 78)
        emit(f"[{number}/{len(posts)}] {post.title[:100]}")
        # The feed already spells the author as "/u/name"; PRAW and --file do not.
        author = post.author if post.author.startswith("/u/") else f"/u/{post.author}"
        emit(f"  {author} · {post.age()} · {post.url}")
        if post.body:
            body = post.body.replace("\n", " ")
            emit(f"  {body[:220]}{'...' if len(body) > 220 else ''}")
        emit("-" * 78)
        emit(
            f"  {normalized.detection.lang} · top={top:.2f} supporting={supporting} · "
            f"{'REPLY' if result.should_post else 'SILENT'} ({reason})"
        )
        if normalized.english.strip().lower() != post.question.strip().lower():
            emit(f"  as: {normalized.english[:110]}")

        if args.show_hits:
            for hit in result.hits:
                emit(f"    [{hit.score:.2f}] ({hit.record.source}) {hit.record.question[:78]}")

        if result.should_post:
            emit()
            for line in answer_mod.render_comment(result).splitlines():
                emit(f"  | {line}")

    emit()
    emit("=" * 78)
    emit(f"{answered} of {len(posts)} posts would get a reply ({100 * answered / len(posts):.0f}%)")
    for reason, count in sorted(outcomes.items(), key=lambda kv: -kv[1]):
        emit(f"  {count:3}  {reason}")
    emit()
    emit("Too chatty?  raise answer.min_confidence in config.yaml")
    emit("Too quiet?   the corpus is usually the problem, not the threshold")
    emit("A bad answer? find the row with scripts/review_corpus.py and block it")

    if out:
        out.close()
        log.info("Transcript written to %s", args.out)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        raise SystemExit(130) from None
