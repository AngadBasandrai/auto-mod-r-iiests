"""Hybrid retrieval: BM25 + dense, fused with RRF, then an LLM rerank.

Why both halves are needed here specifically:
  * Dense alone fumbles proper nouns — "Sanaka", "SSC", "Part-II", branch codes.
  * BM25 alone fumbles paraphrase and transliteration — "hostel fees kitni hai"
    shares almost no tokens with "What does accommodation cost?".

The query is normalized to English first (lang.normalize_query) and both the
original and the English form are searched, so a Hinglish question finds an
English record and vice versa.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from . import config, groq_client, lang
from .index import store

log = logging.getLogger(__name__)


@dataclass
class Hit:
    record: store.Record
    score: float
    rank: int


RERANK_SYSTEM = """You score how well each candidate FAQ entry answers a student's question
about IIEST Shibpur.

Return JSON: {"scores": [{"id": <candidate id>, "score": 0.0-1.0}]}

Scoring guide:
- 1.0  directly and completely answers the question
- 0.7  answers the main part, or answers it for a closely related case
- 0.4  same topic, does not actually answer what was asked
- 0.0  unrelated, or only superficially shares words

Be strict. A wrong answer posted publicly is worse than no answer. Score every
candidate. Do not invent candidates."""


def _rrf_fuse(
    ranked_lists: list[list[tuple[int, float]]], k: int
) -> dict[int, float]:
    """Reciprocal Rank Fusion — combines rankings without needing comparable scores."""
    fused: dict[int, float] = {}
    for ranked in ranked_lists:
        for rank, (doc_id, _score) in enumerate(ranked, start=1):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (k + rank)
    return fused


def _rerank(query: str, candidates: list[store.Record]) -> dict[int, float]:
    """LLM relevance scores in [0,1], keyed by record id."""
    if not candidates:
        return {}
    listing = "\n\n".join(
        f"[{c.id}] Q: {c.question}\nA: {c.answer[:600]}" for c in candidates
    )
    data = groq_client.chat_json(
        RERANK_SYSTEM,
        f"Student's question:\n{query}\n\nCandidates:\n{listing}",
        kind="fast",
        max_tokens=1024,
        default={"scores": []},
    )
    scores: dict[int, float] = {}
    if isinstance(data, dict):
        for item in data.get("scores", []) or []:
            if not isinstance(item, dict):
                continue
            try:
                doc_id = int(item["id"])
                score = float(item["score"])
            except (KeyError, TypeError, ValueError):
                continue
            scores[doc_id] = max(0.0, min(1.0, score))
    return scores


def search(
    query: str,
    index: store.Index,
    *,
    normalized: lang.NormalizedQuery | None = None,
    rerank: bool = True,
) -> list[Hit]:
    """Return the best records for `query`, most relevant first."""
    normalized = normalized or lang.normalize_query(query)
    cfg = config.get("retrieval", {})

    dense_vector = store.embed_query(normalized.english or query)
    dense = index.dense_search(dense_vector, cfg.get("dense_top_k", 30))

    # Search the original wording and the normalized keywords separately: the
    # first catches Hinglish spellings in the corpus, the second catches the
    # English phrasing.
    lexical_original = index.lexical_search(query, cfg.get("bm25_top_k", 30))
    lexical_english = index.lexical_search(
        " ".join([normalized.english, *normalized.keywords]),
        cfg.get("bm25_top_k", 30),
    )

    fused = _rrf_fuse([dense, lexical_original, lexical_english], cfg.get("rrf_k", 60))
    if not fused:
        return []

    ordered = sorted(fused.items(), key=lambda kv: -kv[1])
    shortlist = [index.records[doc_id] for doc_id, _ in ordered[: cfg.get("rerank_candidates", 12)]]

    final_k = cfg.get("final_k", 5)

    if not rerank:
        return [
            Hit(record=record, score=min(1.0, fused[record.id] * 10), rank=i)
            for i, record in enumerate(shortlist[:final_k])
        ]

    scores = _rerank(normalized.english or query, shortlist)
    if not scores:
        log.warning("Rerank returned nothing; falling back to fused order")
        return [
            Hit(record=record, score=min(1.0, fused[record.id] * 10), rank=i)
            for i, record in enumerate(shortlist[:final_k])
        ]

    reranked = sorted(shortlist, key=lambda r: -scores.get(r.id, 0.0))
    hits = [
        Hit(record=record, score=scores.get(record.id, 0.0), rank=i)
        for i, record in enumerate(reranked[:final_k])
    ]
    return [h for h in hits if h.score > 0]


def confidence(hits: list[Hit]) -> tuple[float, int]:
    """Top score, and how many hits clear half of it (the 'supporting' count)."""
    if not hits:
        return 0.0, 0
    top = hits[0].score
    supporting = sum(1 for h in hits if h.score >= max(0.4, top * 0.5))
    return top, supporting


def is_confident(hits: list[Hit]) -> bool:
    """Gate on the reranked scores. Silence is the default."""
    top, supporting = confidence(hits)
    if top < config.get("answer.min_confidence", 0.7):
        return False
    # One curated entry that nails the question is enough on its own; otherwise
    # we want corroboration before speaking. The student wiki qualifies: it is
    # written as documentation and its entries are quoted verbatim, unlike a
    # chat message that a model had to interpret.
    if top >= 0.9 and hits[0].record.source in {"reddit_wiki", "reddit_pinned", "student_wiki"}:
        return True
    return supporting >= config.get("answer.min_supporting", 2)
