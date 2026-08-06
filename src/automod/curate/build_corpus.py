"""Merge every source into the single committed corpus, data/corpus/qa.jsonl.

Reddit threads convert to Q&A directly (the title is the question, the top
comment is the answer) — no LLM needed and no risk of invention. Wiki pages and
pinned FAQ posts are long documents, so those go through the same extraction
model as the WhatsApp chat.

Everything is scrubbed, confidence-filtered, and near-duplicate collapsed before
it is written.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

from .. import config, groq_client
from ..index import store
from .extract import _validate
from .scrub import scrub_record, scrub_text

log = logging.getLogger(__name__)

DOC_SYSTEM = """You are building an FAQ knowledge base for r/iiests (IIEST Shibpur).
You are given an excerpt from a subreddit wiki page or a pinned FAQ post.

Extract the factual question-answer pairs it contains. Return JSON:

{"pairs": [{"question_en": "...", "question_original": "...", "answer_en": "...",
            "topic": "admissions|academics|hostel|fees|placements|campus|clubs|exams|transfer|general",
            "confidence": 0.0-1.0}]}

Rules:
- Only use information present in the excerpt. Never add outside knowledge.
- Phrase each question the way a student would actually ask it.
- Skip subreddit rules, moderation policy, formatting boilerplate and link dumps.
- Wiki and pinned content is mod-curated, so confidence is usually 0.9.
- Return {"pairs": []} if the excerpt contains no answerable facts."""


def _chunk(text: str, size: int = 4000, overlap: int = 400) -> list[str]:
    """Split a long document on paragraph boundaries where possible."""
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            split = text.rfind("\n\n", start + size // 2, end)
            if split != -1:
                end = split
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def pairs_from_reddit(path: Path | None = None) -> list[dict]:
    """Convert data/corpus/reddit.jsonl into Q&A rows."""
    path = path or config.REDDIT_RAW_PATH
    if not path.exists():
        log.info("No Reddit corpus at %s — skipping", path)
        return []

    pairs: list[dict] = []
    documents: list[dict] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if "text" in row:  # wiki page or pinned post body
            documents.append(row)
            continue
        answer = "\n\n".join(row.get("answers", [])).strip()
        question = row.get("question", "").strip()
        if not answer or not question:
            continue
        pairs.append(
            {
                "question": question[:1500],
                "question_original": row.get("title", "")[:500],
                "answer": answer[:4000],
                "topic": (row.get("flair") or "general").strip().lower() or "general",
                "source": row.get("source", "reddit_thread"),
                "ref": row.get("ref", ""),
                # Upvoted threads are trustworthy but not mod-curated.
                "confidence": 0.8,
            }
        )

    log.info("Reddit: %d thread pairs, %d documents to extract", len(pairs), len(documents))

    for document in documents:
        for chunk in _chunk(document["text"]):
            data = groq_client.chat_json(
                DOC_SYSTEM,
                f"Source: {document.get('title', '')}\n\n{chunk}",
                kind="fast",
                max_tokens=2048,
                default={"pairs": []},
            )
            extracted = _validate((data or {}).get("pairs") if isinstance(data, dict) else None)
            for pair in extracted:
                pair["source"] = document.get("source", "reddit_wiki")
                pair["ref"] = document.get("ref", "")
            pairs.extend(extracted)

    return [scrub_record(p) for p in pairs]


def dedupe(rows: list[dict], threshold: float | None = None) -> list[dict]:
    """Collapse near-identical questions, keeping the most trustworthy copy.

    Greedy: rows are sorted by confidence, then each row is dropped if it is too
    close to a row already kept. With a few thousand rows the full similarity
    matrix is cheap and exact.
    """
    if len(rows) < 2:
        return rows
    threshold = threshold if threshold is not None else config.get("curate.dedupe_threshold", 0.93)

    order = sorted(range(len(rows)), key=lambda i: -float(rows[i].get("confidence", 0)))
    vectors = store.embed_passages([rows[i]["question"] for i in order])

    kept_indices: list[int] = []
    kept_vectors: list[np.ndarray] = []
    for position, row_index in enumerate(order):
        vector = vectors[position]
        if kept_vectors:
            similarity = np.asarray(kept_vectors) @ vector
            if float(similarity.max()) >= threshold:
                continue
        kept_indices.append(row_index)
        kept_vectors.append(vector)

    kept = [rows[i] for i in sorted(kept_indices)]
    log.info("Dedupe: %d -> %d rows (threshold %.2f)", len(rows), len(kept), threshold)
    return kept


def build(
    whatsapp_pairs: list[dict] | None = None,
    reddit_pairs: list[dict] | None = None,
    out_path: Path | None = None,
) -> Path:
    """Filter, merge, dedupe and write the committed corpus."""
    out_path = out_path or config.QA_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    min_confidence = config.get("curate.min_confidence", 0.6)

    rows = list(whatsapp_pairs or []) + list(reddit_pairs or [])
    before = len(rows)
    rows = [r for r in rows if float(r.get("confidence", 0)) >= min_confidence]
    log.info("Confidence filter (>=%.2f): %d -> %d rows", min_confidence, before, len(rows))

    rows = dedupe(rows)

    # Belt and braces: nothing reaches a committed file unscrubbed.
    rows = [scrub_record(r) for r in rows]
    for row in rows:
        row["answer"] = scrub_text(row["answer"])

    with out_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    by_source: dict[str, int] = {}
    for row in rows:
        by_source[row.get("source", "?")] = by_source.get(row.get("source", "?"), 0) + 1
    log.info("Wrote %d rows -> %s  %s", len(rows), out_path, by_source)
    return out_path


def load_corpus(path: Path | None = None) -> list[dict]:
    path = path or config.QA_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"No corpus at {path}. Run the ingest scripts first "
            "(scripts/ingest_whatsapp.py, scripts/ingest_reddit.py)."
        )
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
