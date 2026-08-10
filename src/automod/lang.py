"""Language handling for Hindi / English / romanized Hinglish.

Two layers:
  * `detect()` -- cheap, offline, deterministic. Enough to decide which script the
    reply should be written in and to label corpus rows. Safe to unit test.
  * `normalize_query()` -- one small LLM call that canonicalizes a question into
    English plus keyword variants, so dense retrieval has something stable to
    embed and BM25 gets alternate spellings ("hostal", "hostel", "chhatravas").
"""

from __future__ import annotations

import functools
import logging
import re
from dataclasses import dataclass, field

from . import groq_client

log = logging.getLogger(__name__)

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
LATIN = re.compile(r"[A-Za-z]")

# High-signal romanized Hindi tokens.
#
# Every entry here must be a word that essentially never appears in an English
# sentence. That rules out some genuinely common Hindi words -- "the" (past
# tense), "he", "hi", "mere", "mat", "par" -- because they collide with English
# and would misroute plain English questions into Hinglish replies. Likewise
# "fees" and "admission" are English, not markers, however often they appear in
# this chat. Precision matters more than recall: two markers are required to
# trigger, and the LLM normalizer handles whatever this misses.
HINGLISH_MARKERS = frozenset(
    """
    hai hain haii hei hoga hogi honge hota hoti hote tha thi
    kya kyu kyun kyon kaise kese kaisa kaisi kab kahan kahaan kaha
    kitna kitni kitne kaun konsa kaunsa kon
    nahi nahin nhi nai bilkul kuch koi sab sabhi
    mujhe mujhko mera meri hamara hamari tumhara tumhari aapka aapki
    apna apni uska uski unka unki iska iski
    karo karna karta karti karte krna kro karke krke
    milega milegi milta milti chahiye chaiye
    bhai bhaiya yaar bhii toh tho
    accha acha theek thik sahi galat matlab bata batao batado
    pata lagta lagega jyada zyada thoda bohot bahut bhot
    agar lekin magar phir fir waise abhi aaj kal jaldi
    zaroori zaruri chalega samajh dekho suno
    rehna rehne khana padhai padhna andar bahar
    """.split()
)


@dataclass
class Detection:
    lang: str  # "hi" | "en" | "hinglish"
    script: str  # "deva" | "latin" | "mixed"
    is_transliterated: bool
    marker_hits: list[str] = field(default_factory=list)

    @property
    def reply_style(self) -> str:
        """Human-readable instruction for the answer prompt."""
        return {
            "hi": "Hindi, written in Devanagari script",
            "hinglish": "romanized Hinglish (Hindi words in Latin script, mixed with English) — match the casual tone of the question",
            "en": "English",
        }[self.lang]


def detect(text: str) -> Detection:
    """Offline language/script detection. No network."""
    text = text or ""
    deva = len(DEVANAGARI.findall(text))
    latin = len(LATIN.findall(text))

    words = re.findall(r"[a-z]+", text.lower())
    hits = sorted({w for w in words if w in HINGLISH_MARKERS})

    if deva and latin:
        script = "mixed"
    elif deva:
        script = "deva"
    else:
        script = "latin"

    # Devanagari present in any real quantity -> answer in Hindi script.
    if deva >= 3 and deva >= latin // 4:
        return Detection("hi", script, False, hits)

    # Two independent romanized-Hindi markers is a reliable Hinglish signal;
    # one is common in otherwise-English posts ("bhai anyone know...").
    if len(hits) >= 2:
        return Detection("hinglish", script, True, hits)

    return Detection("en", script, False, hits)


_NORMALIZE_SYSTEM = """You normalize questions asked by Indian engineering college students on Reddit.
The question may be in English, Hindi (Devanagari), romanized Hindi written in Latin
letters ("Hinglish"), or any mix. Spelling is often inconsistent.

Return ONLY a JSON object:
{
  "english_query": "the question restated as a clear, standalone English question",
  "keywords": ["3-8 short search terms"],
  "topic": "one of: admissions, academics, hostel, fees, placements, campus, clubs, exams, transfer, general",
  "is_question": true or false
}

Rules:
- "english_query" must preserve the exact intent. Do not answer it, do not add facts.
- "english_query" is a RESTATEMENT of the text you were given. Never replace it
  with a different question, however plausible. If the text is vague, restate it
  vaguely — "give a summary of faqs about iiest" becomes "What are the frequently
  asked questions about IIEST?", never "What is the average package for CSE?".
  Inventing a specific question the user did not ask is the worst failure here,
  because everything downstream then answers the wrong thing confidently.
- "keywords" must include BOTH the English term and the romanized Hindi term when
  they differ, plus likely misspellings a student would type. Example: for
  "hostel fees kitni hai" -> ["hostel fee", "hostal fees", "hostel charges", "chhatravas", "mess fees"].
- Set "is_question" to false unless the author is genuinely ASKING something.
  Set it to false for a rant, announcement, meme, greeting, poll, or a broad
  request to summarize. Most importantly, set it to false when the author is
  SHARING or SHOWING something they made or found:
    "Introducing, IIEST-Chan"      -> sharing artwork. false.
    "Campus map" + "made this, open for suggestions" -> sharing work. false.
    "Got into IIEST finally!!"     -> celebrating. false.
    "Rate my schedule"             -> asking for opinions, not facts. false.
  A post can invite comments ("open for suggestions", "thoughts?") without
  asking a factual question. Inviting discussion is not asking a question.
  When the post is someone presenting their own work, the only honest reply is
  none, so is_question must be false."""


@dataclass
class NormalizedQuery:
    original: str
    english: str
    keywords: list[str]
    topic: str
    is_question: bool
    detection: Detection


# Words carrying no topic signal, so their presence or absence says nothing about
# whether two phrasings are the same question.
_STOPWORDS = frozenset(
    """
    the a an of for in on at to is are was were be been being do does did done
    what which who whom whose when where why how can could should would will
    and or but if then than that this these those it its as by with from about
    any some all my your our their there here get got give given tell me please
    know need want much many more most good best
    """.split()
)


def content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 2 and w not in _STOPWORDS}


def _looks_substituted(original: str, english: str, detection: Detection) -> bool:
    """Did the model answer a different question than the one it was given?

    Observed in practice: "give a summary of faqs asked regarding iiest" came
    back as "What is the average package offered to CSE students in IIEST?".
    Retrieval then scored 1.00 against a question nobody asked.

    Measured over the RESTATEMENT's words, not the original's. A Reddit post is
    a title plus several paragraphs; a restated question is one sentence, so it
    can never contain much of a long post and scoring it that way flagged
    perfectly good restatements — "Hey someone plz tell kya character certificate
    required hai ya nhi ..." became "Is a character certificate required for
    admission?" and was thrown away. The right question is the other one: does
    the restatement bring its own nouns, or reuse the ones it was given.

    Only applied to Latin-script input. Translating Devanagari legitimately
    shares no words with the source — "छात्रावास का शुल्क कितना है?" and "What is
    the hostel fee?" have zero overlap and that is correct.
    """
    if detection.script != "latin":
        return False
    source = content_words(original)
    restated = content_words(english)
    if not source or not restated:
        return False
    return len(restated & source) / len(restated) < 0.25


@functools.lru_cache(maxsize=512)
def _normalize_cached(text: str) -> tuple[str, tuple[str, ...], str, bool]:
    data = groq_client.chat_json(
        _NORMALIZE_SYSTEM,
        text[:4000],
        kind="fast",
        max_tokens=512,
        default={},
    )
    if not isinstance(data, dict):
        data = {}
    english = str(data.get("english_query") or text).strip()
    keywords = [str(k) for k in (data.get("keywords") or []) if str(k).strip()]
    topic = str(data.get("topic") or "general")
    is_question = bool(data.get("is_question", True))
    return english, tuple(keywords), topic, is_question


def normalize_query(text: str) -> NormalizedQuery:
    """Canonicalize a user question. Falls back to the raw text if Groq fails."""
    detection = detect(text)
    try:
        english, keywords, topic, is_question = _normalize_cached(text.strip())
    except Exception:  # noqa: BLE001 - retrieval must still work without normalization
        english, keywords, topic, is_question = text.strip(), (), "general", True

    if _looks_substituted(text, english, detection):
        # The whole response is suspect once the question has been swapped —
        # the keywords describe the invented question too. Fall back to the raw
        # text, which BM25 and the embedder both handle on their own.
        log.warning(
            "Normalizer substituted a different question; ignoring it. %r -> %r",
            text.strip()[:80],
            english[:80],
        )
        english, keywords = text.strip(), ()

    return NormalizedQuery(
        original=text,
        english=english,
        keywords=list(keywords),
        topic=topic,
        is_question=is_question,
        detection=detection,
    )
