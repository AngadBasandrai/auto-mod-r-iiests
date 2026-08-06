"""Build the search index from the committed corpus."""

from __future__ import annotations

import logging
from pathlib import Path

from .. import config
from ..curate.build_corpus import load_corpus
from . import store

log = logging.getLogger(__name__)


def run(corpus_path: Path | None = None, index_dir: Path | None = None) -> store.Index:
    rows = load_corpus(corpus_path)
    log.info("Building index over %d corpus rows", len(rows))
    index = store.build(rows)
    index.save(index_dir or config.INDEX_DIR)
    return index
