"""Grounded answer generation.

Two guarantees this module is responsible for:
  1. Nothing is stated that isn't in the retrieved context. The model is told to
     abstain, and it gets a structured "answerable" flag it can set to false —
     that flag is a second gate on top of the retrieval score.
  2. The reply comes back in the language and script the question used, because
     answering a Hinglish question in formal English reads like a bot.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from . import config, groq_client, lang
from .index.store import Index
from .retrieve import Hit, confidence, is_confident, search

log = logging.getLogger(__name__)

SYSTEM = """You answer questions from students about IIEST Shibpur, on the subreddit
r/iiests. You are given context entries drawn from the subreddit's own FAQ, wiki
and past threads, plus knowledge shared by current students.

Return JSON:
{
  "answerable": true or false,
  "answer": "your reply, or empty string if not answerable",
  "used_refs": [list of context ids you actually used]
}

Absolute rules:
- Use ONLY the context. If it does not contain the answer, set "answerable" to
  false and leave "answer" empty. Never fill a gap with general knowledge about
  Indian colleges, and never guess a number.
- If the context partially answers the question, answer only the part it covers
  and say plainly what you don't know.
- Never invent fees, dates, cutoffs, ranks, names or contact details.

Style:
- Write the reply in {language}.
- Reddit comment: 2-5 short sentences or a few bullets. No greeting, no sign-off,
  no "based on the context provided".
- Be concrete and direct. Lead with the answer.
- If the context suggests the figure may be outdated, add a short caveat.
- Plain Reddit markdown only."""


@dataclass
class Answer:
    text: str
    hits: list[Hit]
    confident: bool
    top_score: float
    supporting: int
    reason: str = ""

    @property
    def should_post(self) -> bool:
        return self.confident and bool(self.text.strip())


def _format_context(hits: list[Hit]) -> str:
    blocks = []
    for hit in hits:
        record = hit.record
        origin = {
            "reddit_wiki": "subreddit wiki",
            "reddit_pinned": "pinned FAQ post",
            "reddit_thread": "past thread",
            "whatsapp": "student community knowledge",
        }.get(record.source, record.source)
        blocks.append(
            f"[{record.id}] (source: {origin}, relevance {hit.score:.2f})\n"
            f"Q: {record.question}\n"
            f"A: {record.answer[:1200]}"
        )
    return "\n\n".join(blocks)


def _sources_line(hits: list[Hit], used: set[int]) -> str:
    links = []
    for hit in hits:
        if used and hit.record.id not in used:
            continue
        ref = hit.record.ref or ""
        if ref.startswith("http") and ref not in links:
            links.append(ref)
    if not links:
        return ""
    return "\n\n" + " · ".join(f"[source]({url})" for url in links[:3])


def generate(
    question: str,
    index: Index,
    *,
    normalized: lang.NormalizedQuery | None = None,
    hits: list[Hit] | None = None,
) -> Answer:
    """Retrieve, gate, and generate. Returns an Answer that may be unpostable."""
    normalized = normalized or lang.normalize_query(question)

    if not normalized.is_question:
        return Answer("", [], False, 0.0, 0, reason="not a question")

    hits = hits if hits is not None else search(question, index, normalized=normalized)
    top_score, supporting = confidence(hits)

    if not hits:
        return Answer("", [], False, 0.0, 0, reason="no retrieval hits")
    if not is_confident(hits):
        return Answer(
            "", hits, False, top_score, supporting, reason="below confidence threshold"
        )

    system = SYSTEM.replace("{language}", normalized.detection.reply_style)
    user = (
        f"Student's question (as asked):\n{question.strip()[:2000]}\n\n"
        f"Same question in English:\n{normalized.english}\n\n"
        f"Context entries:\n{_format_context(hits)}"
    )

    data = groq_client.chat_json(
        system, user, kind="strong", temperature=0.3, max_tokens=900, default={}
    )
    if not isinstance(data, dict):
        data = {}

    if not data.get("answerable"):
        return Answer(
            "", hits, False, top_score, supporting, reason="model declined to answer"
        )

    text = str(data.get("answer") or "").strip()
    if len(text) < 20:
        return Answer("", hits, False, top_score, supporting, reason="answer too short")

    max_chars = config.get("answer.max_answer_chars", 1800)
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + "…"

    used = set()
    for value in data.get("used_refs", []) or []:
        try:
            used.add(int(value))
        except (TypeError, ValueError):
            continue

    text += _sources_line(hits, used)
    return Answer(text, hits, True, top_score, supporting, reason="ok")


def render_comment(answer: Answer) -> str:
    """The full Reddit comment body, including the bot footer."""
    footer = config.get("answer.footer", "") or ""
    return answer.text.rstrip() + "\n" + footer.rstrip() + "\n"
