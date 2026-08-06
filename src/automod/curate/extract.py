"""Turn noisy conversation windows into clean Q&A records.

This is the step that solves "the export has irrelevant data". Instead of
indexing the chat and hoping retrieval avoids the banter, a cheap model reads
each window and emits only durable, factual Q&A about IIEST. Everything else —
jokes, meetup planning, arguments, one-word replies — returns an empty list and
disappears before it ever reaches the index.

Results are cached on disk by window hash, so re-runs after a prompt tweak only
pay for what changed.
"""

from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable

from .. import config, groq_client
from .scrub import scrub_record
from .sessionize import Window

log = logging.getLogger(__name__)

SYSTEM = """You are building an FAQ knowledge base for r/iiests, the subreddit of IIEST
Shibpur (an engineering college in India). You are reading a window of a student
WhatsApp group chat.

The chat is in English, Hindi (Devanagari), romanized Hindi in Latin letters
("Hinglish"), or a mix. Spelling is inconsistent and messages are fragmented
across several lines.

Extract ONLY durable, factual question-answer pairs that would help a future
student. Return this JSON object:

{"pairs": [
  {
    "question_en": "clear standalone question in English",
    "question_original": "the question as actually asked in the chat, original wording and script",
    "answer_en": "the answer, in English, self-contained, no chat references",
    "topic": "admissions|academics|hostel|fees|placements|campus|clubs|exams|transfer|general",
    "confidence": 0.0 to 1.0
  }
]}

Return {"pairs": []} — this is the common and correct outcome — when the window is:
- banter, jokes, memes, insults, flirting, emoji-only exchanges
- planning meetups, "where are you", "coming?", "kis ne khana khaya"
- arguments, politics, personal drama, gossip about specific people
- links with no explanation, forwarded messages, spam
- questions that were asked but never actually answered
- opinions with no factual content ("X branch is trash")
- anything time-sensitive that expires (today's class timing, a specific event date)

Hard rules:
- The answer must be supported by the chat. Never add outside knowledge.
- If several people gave conflicting answers, only extract it if a clear
  consensus or a correction emerged; otherwise skip it.
- "confidence" reflects how certain and well-supported the answer is. Use below
  0.6 when it was a guess, hearsay, or one person's unconfirmed claim.
- Never include names, phone numbers, usernames, or "User1 said". Write answers
  impersonally.
- Rewrite answers as complete sentences. "yes 12k" becomes "The hostel fee is
  approximately Rs 12,000."
- Prefer few high-quality pairs over many weak ones. Most windows yield zero."""

_write_lock = threading.Lock()


class ExtractionCache:
    """Append-only JSONL cache keyed by window hash."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, list[dict]] = {}
        if self.path.exists():
            with self.path.open(encoding="utf-8") as fh:
                for line in fh:
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    self._data[row["key"]] = row["pairs"]
            log.info("Loaded %d cached windows from %s", len(self._data), self.path.name)

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def get(self, key: str) -> list[dict]:
        return self._data.get(key, [])

    def put(self, key: str, pairs: list[dict]) -> None:
        with _write_lock:
            self._data[key] = pairs
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"key": key, "pairs": pairs}, ensure_ascii=False) + "\n")


def _validate(pairs: object) -> list[dict]:
    """Keep only well-formed pairs; the model occasionally improvises."""
    if not isinstance(pairs, list):
        return []
    out: list[dict] = []
    for item in pairs:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question_en") or "").strip()
        answer = str(item.get("answer_en") or "").strip()
        if len(question) < 8 or len(answer) < 15:
            continue
        try:
            confidence = float(item.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        out.append(
            {
                "question": question,
                "question_original": str(item.get("question_original") or question).strip(),
                "answer": answer,
                "topic": str(item.get("topic") or "general").strip().lower(),
                "confidence": max(0.0, min(1.0, confidence)),
            }
        )
    return out


def extract_window(window: Window) -> list[dict]:
    """One Groq call. Returns validated, scrubbed pairs."""
    transcript = window.render()
    if len(transcript) < 60:
        return []
    data = groq_client.chat_json(
        SYSTEM,
        f"Conversation window ({window.start:%d %b %Y} to {window.end:%d %b %Y}):\n\n{transcript[:12000]}",
        kind="fast",
        max_tokens=2048,
        default={"pairs": []},
    )
    pairs = _validate((data or {}).get("pairs") if isinstance(data, dict) else None)
    for pair in pairs:
        pair["source"] = "whatsapp"
        pair["ref"] = f"chat {window.start:%b %Y}"
        pair["window"] = window.key
    return [scrub_record(p) for p in pairs]


def extract_all(
    windows: Iterable[Window],
    *,
    cache_path: Path | None = None,
    workers: int | None = None,
    progress_every: int = 25,
) -> list[dict]:
    """Extract from every window, in parallel, resuming from cache."""
    windows = list(windows)
    cache = ExtractionCache(cache_path or config.CACHE_DIR / "extract_cache.jsonl")
    workers = workers or config.get("curate.extract_workers", 8)

    todo = [w for w in windows if w.key not in cache]
    log.info(
        "Extracting: %d windows total, %d cached, %d to process (%d workers)",
        len(windows),
        len(windows) - len(todo),
        len(todo),
        workers,
    )

    done = 0
    if todo:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(extract_window, w): w for w in todo}
            for future in as_completed(futures):
                window = futures[future]
                try:
                    pairs = future.result()
                except Exception as exc:  # noqa: BLE001 - one bad window must not kill the run
                    log.warning("Window %s failed: %s", window.key, exc)
                    pairs = []
                cache.put(window.key, pairs)
                done += 1
                if done % progress_every == 0:
                    log.info("  %d/%d windows", done, len(todo))

    results: list[dict] = []
    for window in windows:
        results.extend(cache.get(window.key))
    log.info("Extracted %d raw pairs from %d windows", len(results), len(windows))
    return results
