"""Embedding model + on-disk hybrid index.

Groq has no embeddings endpoint, so vectors come from fastembed, which runs the
model through ONNX Runtime — no PyTorch, ~50 MB install, and it works the same on
this machine and on a GitHub Actions runner.

The corpus is a few thousand rows, so the "vector database" is a numpy array and
a cosine dot product. Anything heavier would be pure ceremony.
"""

from __future__ import annotations

import json
import logging
import pickle
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .. import config

log = logging.getLogger(__name__)

_embedder = None
_embedder_name: str | None = None

_TOKEN_RE = re.compile(r"[a-z0-9ऀ-ॿ]+")


def tokenize(text: str) -> list[str]:
    """Shared tokenizer for BM25. Keeps Devanagari as well as Latin/digits."""
    return _TOKEN_RE.findall((text or "").lower())


def _resolve_model() -> str:
    """First configured embedding model that fastembed actually supports."""
    from fastembed import TextEmbedding

    supported = {m["model"] for m in TextEmbedding.list_supported_models()}
    for candidate in config.get("embedding.candidates", []):
        if candidate in supported:
            return candidate
    raise RuntimeError(
        "None of the configured embedding models are supported by this fastembed "
        f"version. Configured: {config.get('embedding.candidates')}. "
        f"Available: {sorted(supported)[:20]}..."
    )


def embedder():
    """Lazily loaded fastembed model (downloads once, then cached on disk)."""
    global _embedder, _embedder_name
    if _embedder is None:
        from fastembed import TextEmbedding

        _embedder_name = _resolve_model()
        log.info("Loading embedding model %s", _embedder_name)
        _embedder = TextEmbedding(
            model_name=_embedder_name,
            cache_dir=str(config.ROOT / ".fastembed_cache"),
        )
    return _embedder


def model_name() -> str:
    embedder()
    return _embedder_name or "unknown"


def _prefix(kind: str) -> str:
    """e5 models need query:/passage: prefixes; others must not have them."""
    if "e5" not in model_name().lower():
        return ""
    return config.get(f"embedding.{kind}_prefix", "") or ""


def embed_passages(texts: list[str]) -> np.ndarray:
    prefix = _prefix("passage")
    vectors = list(embedder().embed([prefix + t for t in texts]))
    return _normalize(np.asarray(vectors, dtype=np.float32))


def embed_query(text: str) -> np.ndarray:
    prefix = _prefix("query")
    vector = next(iter(embedder().embed([prefix + text])))
    return _normalize(np.asarray([vector], dtype=np.float32))[0]


def _normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


@dataclass
class Record:
    id: int
    question: str
    question_original: str
    answer: str
    topic: str
    source: str
    ref: str
    confidence: float

    @classmethod
    def from_dict(cls, index: int, row: dict) -> "Record":
        return cls(
            id=index,
            question=row.get("question", ""),
            question_original=row.get("question_original") or row.get("question", ""),
            answer=row.get("answer", ""),
            topic=row.get("topic", "general"),
            source=row.get("source", "unknown"),
            ref=row.get("ref", ""),
            confidence=float(row.get("confidence", 1.0)),
        )

    def embed_text(self) -> str:
        return f"{self.question}\n{self.answer}"

    def lexical_text(self) -> str:
        """Both spellings go in, so Hinglish and English queries both hit."""
        return f"{self.question_original}\n{self.question}\n{self.answer}\n{self.topic}"


class Index:
    def __init__(self, records: list[Record], vectors: np.ndarray, bm25) -> None:
        self.records = records
        self.vectors = vectors
        self.bm25 = bm25

    def __len__(self) -> int:
        return len(self.records)

    # -- persistence --------------------------------------------------------
    def save(self, directory: Path | None = None) -> Path:
        directory = directory or config.INDEX_DIR
        directory.mkdir(parents=True, exist_ok=True)
        np.save(directory / "vectors.npy", self.vectors)
        with (directory / "records.jsonl").open("w", encoding="utf-8") as fh:
            for record in self.records:
                fh.write(json.dumps(record.__dict__, ensure_ascii=False) + "\n")
        with (directory / "bm25.pkl").open("wb") as fh:
            pickle.dump(self.bm25, fh)
        (directory / "meta.json").write_text(
            json.dumps(
                {
                    "model": model_name(),
                    "records": len(self.records),
                    "dim": int(self.vectors.shape[1]) if self.vectors.size else 0,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        log.info("Saved index with %d records -> %s", len(self.records), directory)
        return directory

    @classmethod
    def load(cls, directory: Path | None = None) -> "Index":
        directory = directory or config.INDEX_DIR
        records_path = directory / "records.jsonl"
        if not records_path.exists():
            raise FileNotFoundError(
                f"No index at {directory}. Run: python scripts/build_index.py"
            )
        records = [
            Record(**json.loads(line))
            for line in records_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        vectors = np.load(directory / "vectors.npy")
        with (directory / "bm25.pkl").open("rb") as fh:
            bm25 = pickle.load(fh)
        return cls(records, vectors, bm25)

    # -- search -------------------------------------------------------------
    def dense_search(self, query_vector: np.ndarray, top_k: int) -> list[tuple[int, float]]:
        if not len(self.records):
            return []
        scores = self.vectors @ query_vector
        top = np.argsort(-scores)[:top_k]
        return [(int(i), float(scores[i])) for i in top]

    def lexical_search(self, query: str, top_k: int) -> list[tuple[int, float]]:
        if not len(self.records):
            return []
        tokens = tokenize(query)
        if not tokens:
            return []
        scores = np.asarray(self.bm25.get_scores(tokens))
        top = np.argsort(-scores)[:top_k]
        return [(int(i), float(scores[i])) for i in top if scores[i] > 0]


def build(rows: list[dict]) -> Index:
    """Build an Index from corpus rows."""
    from rank_bm25 import BM25Okapi

    records = [Record.from_dict(i, row) for i, row in enumerate(rows)]
    if not records:
        raise ValueError("Cannot build an index from an empty corpus")

    vectors = embed_passages([r.embed_text() for r in records])
    bm25 = BM25Okapi([tokenize(r.lexical_text()) for r in records])
    return Index(records, vectors, bm25)
