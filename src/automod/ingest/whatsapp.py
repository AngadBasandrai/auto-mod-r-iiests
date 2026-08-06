"""Parse a WhatsApp chat export into structured messages.

WhatsApp exports differ by platform and locale, so we match a family of header
shapes rather than one:

    Android : 06/08/26, 14:32 - Angad: hostel fees kitni hai
    Android : 6/8/2026, 2:32 pm - Angad: ...
    iOS     : [06/08/2026, 2:32:41 PM] Angad: ...
    iOS     : [6/8/26, 14:32:41] Angad: ...

Lines that don't start a new message are continuations of the previous one.
System notices (joins, leaves, "<Media omitted>", the E2E banner) are dropped —
they are never a source of answers and they poison the extraction prompt.

Dates are parsed leniently: day-first is assumed (the Indian/EU default WhatsApp
uses here), falling back to month-first when day-first is impossible.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterator

log = logging.getLogger(__name__)

# Leading LTR/RTL marks appear in iOS exports and break naive matching.
_INVISIBLE = dict.fromkeys(map(ord, "‎‏‪‫‬﻿"))

_DATE = r"(?P<date>\d{1,4}[/.-]\d{1,2}[/.-]\d{2,4})"
_TIME = r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?(?:\s?[APap][. ]?[Mm][.]?)?)"

HEADER_PATTERNS = (
    # iOS: [date, time] Sender: body
    re.compile(rf"^\[{_DATE},\s*{_TIME}\]\s*(?P<sender>[^:]{{1,80}}?):\s?(?P<body>.*)$"),
    # Android: date, time - Sender: body
    re.compile(rf"^{_DATE},\s*{_TIME}\s+-\s+(?P<sender>[^:]{{1,80}}?):\s?(?P<body>.*)$"),
)

# Same shapes but with no "Sender:" -- these are system notices.
SYSTEM_PATTERNS = (
    re.compile(rf"^\[{_DATE},\s*{_TIME}\]\s*(?P<body>.*)$"),
    re.compile(rf"^{_DATE},\s*{_TIME}\s+-\s+(?P<body>.*)$"),
)

SYSTEM_MARKERS = (
    "messages and calls are end-to-end encrypted",
    "created group",
    "added you",
    "changed the subject",
    "changed this group's icon",
    "changed the group description",
    "changed their phone number",
    "changed to ",
    "joined using this group's invite link",
    "left",
    "removed",
    "was added",
    "you were added",
    "deleted this message",
    "this message was deleted",
    "missed voice call",
    "missed video call",
    "security code changed",
    "turned on disappearing messages",
    "pinned a message",
)

# Content-free bodies.
NOISE_BODIES = frozenset(
    {
        "<media omitted>",
        "<attached>",
        "image omitted",
        "video omitted",
        "audio omitted",
        "sticker omitted",
        "gif omitted",
        "document omitted",
        "contact card omitted",
        "this message was deleted",
        "you deleted this message",
        "null",
        "",
    }
)

TIME_FORMATS = (
    "%H:%M:%S",
    "%H:%M",
    "%I:%M:%S %p",
    "%I:%M %p",
)


@dataclass
class Message:
    ts: datetime
    sender: str
    text: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ts"] = self.ts.isoformat()
        return d


def _clean(line: str) -> str:
    return line.translate(_INVISIBLE).rstrip("\n\r")


def _parse_time(raw: str) -> tuple[int, int, int]:
    normalized = re.sub(r"\s+", " ", raw.strip().upper().replace(".", ""))
    for fmt in TIME_FORMATS:
        try:
            t = datetime.strptime(normalized, fmt)
            return t.hour, t.minute, t.second
        except ValueError:
            continue
    return 0, 0, 0


def _parse_date(raw: str) -> tuple[int, int, int] | None:
    parts = re.split(r"[/.-]", raw)
    if len(parts) != 3:
        return None
    try:
        a, b, c = (int(p) for p in parts)
    except ValueError:
        return None

    # ISO-ish: 2026-08-06
    if a > 31:
        return a, b, c

    year = c if c > 99 else 2000 + c
    # Day-first is WhatsApp's default in India/EU. Fall back to month-first only
    # when day-first is impossible.
    if a <= 31 and b <= 12:
        return year, b, a
    if b <= 31 and a <= 12:
        return year, a, b
    return None


def _to_datetime(date_raw: str, time_raw: str) -> datetime | None:
    date_parts = _parse_date(date_raw)
    if not date_parts:
        return None
    year, month, day = date_parts
    hour, minute, second = _parse_time(time_raw)
    try:
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None


def _is_system(body: str) -> bool:
    lowered = body.strip().lower()
    return any(marker in lowered for marker in SYSTEM_MARKERS)


def _is_noise(text: str) -> bool:
    stripped = text.strip().lower()
    if stripped in NOISE_BODIES:
        return True
    # "<Media omitted>" sometimes arrives with a caption; keep those.
    if stripped.startswith("<") and stripped.endswith("omitted>"):
        return True
    return False


def parse_text(content: str) -> list[Message]:
    """Parse the full text of an export into messages."""
    messages: list[Message] = []
    current: Message | None = None
    skipped_headers = 0

    for raw_line in content.splitlines():
        line = _clean(raw_line)
        if not line.strip() and current is None:
            continue

        header = None
        for pattern in HEADER_PATTERNS:
            header = pattern.match(line)
            if header:
                break

        if header:
            ts = _to_datetime(header.group("date"), header.group("time"))
            if ts is None:
                skipped_headers += 1
                continue
            sender = header.group("sender").strip()
            body = header.group("body")
            if _is_system(body) or _is_system(sender):
                current = None
                continue
            current = Message(ts=ts, sender=sender, text=body)
            messages.append(current)
            continue

        # A dateline with no sender is a system notice; it ends the current message.
        if any(p.match(line) for p in SYSTEM_PATTERNS):
            current = None
            continue

        # Continuation line.
        if current is not None:
            current.text += "\n" + line

    if skipped_headers:
        log.warning("Skipped %d lines with unparseable timestamps", skipped_headers)

    cleaned = [m for m in messages if not _is_noise(m.text)]
    for m in cleaned:
        m.text = m.text.strip()
    cleaned = [m for m in cleaned if m.text]
    cleaned.sort(key=lambda m: m.ts)

    log.info(
        "Parsed %d messages (%d raw, %d dropped as noise/system)",
        len(cleaned),
        len(messages),
        len(messages) - len(cleaned),
    )
    return cleaned


def parse_file(path: Path) -> list[Message]:
    content = path.read_text(encoding="utf-8", errors="replace")
    return parse_text(content)


def load_all(directory: Path) -> list[Message]:
    """Parse every .txt export in `directory`, merged and sorted by time."""
    files = sorted(directory.glob("*.txt"))
    if not files:
        raise FileNotFoundError(
            f"No .txt WhatsApp export found in {directory}. "
            "Export the chat from WhatsApp ('Export chat' -> 'Without media') "
            "and drop the .txt file there."
        )
    messages: list[Message] = []
    for path in files:
        log.info("Reading %s", path.name)
        messages.extend(parse_file(path))
    messages.sort(key=lambda m: m.ts)
    return messages


def iter_senders(messages: list[Message]) -> Iterator[str]:
    seen: set[str] = set()
    for m in messages:
        if m.sender not in seen:
            seen.add(m.sender)
            yield m.sender
