"""Group a flat message list into conversation windows.

A question and its answer are usually a few messages apart, so the unit of
extraction is a window rather than a message. Windows break on a long silence or
a message-count cap, and carry a small overlap so a question sitting at a
boundary keeps the reply that follows it.

Sender names are replaced with stable pseudonyms here — the extraction model
never sees real names, which removes the largest PII leak by construction.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import timedelta

from ..ingest.whatsapp import Message


@dataclass
class Window:
    messages: list[Message]
    speakers: dict[str, str] = field(default_factory=dict)

    @property
    def start(self):
        return self.messages[0].ts

    @property
    def end(self):
        return self.messages[-1].ts

    @property
    def key(self) -> str:
        """Stable hash of the content — used to cache extraction results."""
        digest = hashlib.sha256()
        for m in self.messages:
            digest.update(m.ts.isoformat().encode())
            digest.update(m.text.encode("utf-8", "replace"))
        return digest.hexdigest()[:20]

    def render(self) -> str:
        """Pseudonymized transcript for the extraction prompt."""
        lines = []
        for m in self.messages:
            alias = self.speakers.get(m.sender, "User")
            text = m.text.replace("\n", " ").strip()
            lines.append(f"{alias}: {text}")
        return "\n".join(lines)

    def char_len(self) -> int:
        return sum(len(m.text) for m in self.messages)


def _assign_aliases(messages: list[Message]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for m in messages:
        if m.sender not in aliases:
            aliases[m.sender] = f"User{len(aliases) + 1}"
    return aliases


def sessionize(
    messages: list[Message],
    *,
    gap_minutes: int = 45,
    max_messages: int = 25,
    overlap: int = 3,
    min_messages: int = 2,
) -> list[Window]:
    """Split messages into overlapping conversation windows."""
    if not messages:
        return []

    gap = timedelta(minutes=gap_minutes)
    windows: list[Window] = []
    current: list[Message] = []

    def flush(carry_over: bool) -> None:
        nonlocal current
        if len(current) >= min_messages:
            windows.append(Window(messages=list(current), speakers=_assign_aliases(current)))
        current = current[-overlap:] if carry_over and overlap else []

    for message in messages:
        if current and message.ts - current[-1].ts > gap:
            flush(carry_over=False)
        current.append(message)
        if len(current) >= max_messages:
            flush(carry_over=True)

    flush(carry_over=False)
    return windows
