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
and past threads, the student-run IIEST wiki, plus knowledge shared by current
students.

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
- Your reply must add something the poster did not already know. Reusing their
  wording is fine when you are adding a fact from the context — "how many
  sharing room in 1st year" answered with "rooms are 4-sharing" is exactly
  right. But if you would only be summarising their own post back at them,
  adding no fact from the context, set "answerable" to false.

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
            "student_wiki": "IIEST student wiki",
            "whatsapp": "student community knowledge",
        }.get(record.source, record.source)
        blocks.append(
            f"[{record.id}] (source: {origin}, relevance {hit.score:.2f})\n"
            f"Q: {record.question}\n"
            f"A: {record.answer[:1200]}"
        )
    return "\n\n".join(blocks)


# Words that signal someone wants help without saying what about. A post made
# only of these has no subject matter to retrieve against.
_PLEA_WORDS = frozenset(
    """
    help helps helping anyone anybody someone somebody urgent urgently asap
    plz pls please kindly guys bhai bhaiya yaar sir mam maam
    need needed want reply replies answer answers respond response
    question questions doubt doubts query queries ask asking
    advice suggestion suggestions suggest opinion opinions thoughts
    thanks thank thankyou tia advance beforehand appreciated regards
    hello hii hey greetings everyone folks bros dude
    senior seniors junior juniors edit update
    """.split()
)


def has_topic(question: str) -> bool:
    """Does the question say what it is about?

    "URGENT!!!" with a body of "Can anyone help please" is grammatically a
    question and retrieves beautifully — every corpus row mentioning help scores
    high — so the bot answered it with generic reassurance about the office and
    alumni. There was nothing to answer. Strip the pleading and if no subject
    remains, there is no question.
    """
    return bool(lang.content_words(question) - _PLEA_WORDS)


def is_echo(text: str, question: str, threshold: float = 0.8) -> bool:
    """Is this "answer" just the poster's own words handed back?

    The whole design rests on answers coming from retrieved records. A fan-art
    post — "Meet IIEST-Chan, an anthropomorphic version of the IIEST clock
    tower, fully hand drawn and shaded" — retrieved four records about whether
    IIEST is an NIT, and the model replied by restating the post. Nothing in
    that reply came from the context, and the prompt forbidding it was not
    enough, so the check lives here where it is enforced.

    Compared over content words: an answer whose vocabulary is almost entirely
    already in the question has added nothing. A real answer brings the figures
    and nouns that made it worth posting.
    """
    answer_words = lang.content_words(text)
    # Too short to judge — "Yes, it is mandatory." is legitimately made of the
    # question's own words.
    if len(answer_words) < 4:
        return False
    shared = answer_words & lang.content_words(question)
    return len(shared) / len(answer_words) >= threshold


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

    if not has_topic(question):
        return Answer("", [], False, 0.0, 0, reason="no topic in the question")

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

    if is_echo(text, question):
        log.info("Refusing to echo the post back: %.90s", text)
        return Answer(
            "", hits, False, top_score, supporting, reason="answer echoes the question"
        )

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
