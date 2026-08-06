"""PRAW session for the bot account."""

from __future__ import annotations

import logging

import praw

from .. import config

log = logging.getLogger(__name__)


def make_reddit(read_only: bool = False) -> praw.Reddit:
    """Authenticated PRAW client using the script-app password grant."""
    settings = config.settings
    settings.require_reddit()

    reddit = praw.Reddit(
        client_id=settings.reddit_client_id,
        client_secret=settings.reddit_client_secret,
        username=settings.reddit_username,
        password=settings.reddit_password,
        user_agent=settings.reddit_user_agent,
        # PRAW sleeps instead of raising when we approach the rate limit.
        ratelimit_seconds=600,
    )
    reddit.read_only = read_only

    if not read_only:
        me = reddit.user.me()
        if me is None:
            raise RuntimeError(
                "Reddit authentication failed. Check credentials; if the bot account "
                "has 2FA enabled the password must be 'password:TOTPCODE'."
            )
        log.info("Authenticated as u/%s", me.name)
    return reddit


def make_readonly_reddit() -> praw.Reddit:
    """Client-credentials session — enough for ingestion, no bot account needed."""
    settings = config.settings
    if not settings.reddit_client_id or not settings.reddit_client_secret:
        raise RuntimeError("REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET are required")
    reddit = praw.Reddit(
        client_id=settings.reddit_client_id,
        client_secret=settings.reddit_client_secret,
        user_agent=settings.reddit_user_agent,
    )
    reddit.read_only = True
    return reddit
