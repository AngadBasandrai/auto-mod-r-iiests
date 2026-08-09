"""Configuration: secrets from .env, tuning knobs from config.yaml.

Import `settings` for secrets and `cfg()` for the YAML tree. Paths are resolved
relative to the repo root so scripts work from any working directory.
"""

from __future__ import annotations

import functools
import logging
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]

DATA = ROOT / "data"
RAW_DIR = DATA / "raw"
WHATSAPP_DIR = RAW_DIR / "whatsapp"
CACHE_DIR = DATA / "cache"
CORPUS_DIR = DATA / "corpus"
INDEX_DIR = DATA / "index"
STATE_DIR = DATA / "state"

QA_PATH = CORPUS_DIR / "qa.jsonl"
REDDIT_RAW_PATH = CORPUS_DIR / "reddit.jsonl"
WHATSAPP_RAW_PATH = CORPUS_DIR / "whatsapp.jsonl"
WIKI_RAW_PATH = CORPUS_DIR / "wiki.jsonl"
SEEN_PATH = STATE_DIR / "seen.json"
FEEDBACK_PATH = DATA / "feedback.jsonl"

load_dotenv(ROOT / ".env")


class Settings:
    """Secrets and runtime flags, read from the environment."""

    def __init__(self) -> None:
        self.groq_api_key = os.getenv("GROQ_API_KEY", "")
        self.reddit_client_id = os.getenv("REDDIT_CLIENT_ID", "")
        self.reddit_client_secret = os.getenv("REDDIT_CLIENT_SECRET", "")
        self.reddit_username = os.getenv("REDDIT_USERNAME", "")
        self.reddit_password = os.getenv("REDDIT_PASSWORD", "")
        self.reddit_user_agent = os.getenv(
            "REDDIT_USER_AGENT",
            "script:auto-mod-r-iiests:v0.1.0 (by /u/AngadBasandrai)",
        )
        self.dry_run = os.getenv("DRY_RUN", "true").strip().lower() not in {
            "false",
            "0",
            "no",
        }
        self.log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    def require_groq(self) -> str:
        if not self.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is not set (see .env.example)")
        return self.groq_api_key

    def require_reddit(self) -> None:
        missing = [
            name
            for name, value in (
                ("REDDIT_CLIENT_ID", self.reddit_client_id),
                ("REDDIT_CLIENT_SECRET", self.reddit_client_secret),
                ("REDDIT_USERNAME", self.reddit_username),
                ("REDDIT_PASSWORD", self.reddit_password),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"Missing Reddit credentials: {', '.join(missing)}")


settings = Settings()


@functools.lru_cache(maxsize=1)
def cfg() -> dict[str, Any]:
    """The parsed config.yaml tree."""
    with open(ROOT / "config.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def get(path: str, default: Any = None) -> Any:
    """Dotted lookup into config.yaml, e.g. get("answer.min_confidence")."""
    node: Any = cfg()
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def ensure_dirs() -> None:
    for directory in (CACHE_DIR, CORPUS_DIR, INDEX_DIR, STATE_DIR, WHATSAPP_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def setup_logging() -> None:
    # Log lines quote chat text, which is full of emoji and Devanagari. The
    # Windows console is cp1252 by default and would raise on both.
    import sys

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")

    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # PRAW is chatty about rate-limit sleeps at DEBUG.
    logging.getLogger("prawcore").setLevel(logging.WARNING)
