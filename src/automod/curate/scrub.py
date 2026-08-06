"""PII redaction.

Runs on every record before it is written to a committed file. The repo is
public; the WhatsApp export is 284 real people. This module is the last line of
defence and is deliberately aggressive — losing a phone number from an answer is
fine, leaking one is not.

Sender names never reach here: sessionize replaces them with User1/User2 aliases
before the transcript is shown to the model.
"""

from __future__ import annotations

import re

# Indian mobiles (+91 98765 43210, 09876543210, 98765-43210) and generic long runs.
PHONE = re.compile(
    r"""(?<!\w)
    (?:\+?\d{1,3}[\s.-]?)?      # country code
    (?:\(?\d{2,5}\)?[\s.-]?)?   # area / operator
    \d{3,5}[\s.-]?\d{4,6}       # subscriber
    (?!\w)""",
    re.VERBOSE,
)
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
HANDLE = re.compile(r"(?<![\w/])@[A-Za-z_][\w.]{2,}")
# IIEST roll numbers look like 2024CSB012 / 510822010; also catch Aadhaar-ish runs.
ROLL = re.compile(r"\b(?:20\d{2}[A-Z]{2,4}\d{2,4}|\d{9,12})\b")
URL_WITH_SECRET = re.compile(r"https?://\S*(?:token|key|password|auth|session)=\S*", re.I)
# WhatsApp/Telegram invite links point at private groups.
INVITE = re.compile(r"https?://(?:chat\.whatsapp\.com|t\.me)/\S+", re.I)

# Things that look like phone numbers but are legitimate answer content.
_KEEP = re.compile(
    r"^(?:19|20)\d{2}$"        # years
    r"|^\d{1,3}(?:\.\d+)?$"    # small numbers, percentages, CGPA
)


def _redact_phones(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        digits = re.sub(r"\D", "", raw)
        # Fees, ranks, marks and years are numbers we must not destroy.
        if len(digits) < 10:
            return raw
        if _KEEP.match(raw.strip()):
            return raw
        return "[phone]"

    return PHONE.sub(replace, text)


def scrub_text(text: str) -> str:
    """Redact personal identifiers from a single string."""
    if not text:
        return text
    text = EMAIL.sub("[email]", text)
    text = URL_WITH_SECRET.sub("[link]", text)
    text = INVITE.sub("[group-invite]", text)
    text = _redact_phones(text)
    text = ROLL.sub("[id]", text)
    text = HANDLE.sub("[handle]", text)
    return text


def scrub_record(record: dict, fields: tuple[str, ...] = ("question", "answer", "question_original")) -> dict:
    """Return a copy of `record` with the named string fields scrubbed."""
    out = dict(record)
    for field in fields:
        value = out.get(field)
        if isinstance(value, str):
            out[field] = scrub_text(value)
        elif isinstance(value, list):
            out[field] = [scrub_text(v) if isinstance(v, str) else v for v in value]
    return out


def find_leaks(text: str) -> list[str]:
    """Report anything that still looks like PII. Used by the test suite."""
    leaks: list[str] = []
    for name, pattern in (
        ("email", EMAIL),
        ("handle", HANDLE),
        ("invite", INVITE),
    ):
        for match in pattern.finditer(text):
            leaks.append(f"{name}:{match.group(0)}")
    for match in PHONE.finditer(text):
        if len(re.sub(r"\D", "", match.group(0))) >= 10:
            leaks.append(f"phone:{match.group(0)}")
    return leaks
