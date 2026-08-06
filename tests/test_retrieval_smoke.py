"""Integration smoke test for the retrieval half of the pipeline.

Downloads the embedding model on first run (~100 MB) but needs no API key, so it
is opt-in:

    RUN_INTEGRATION=1 python -m pytest tests/test_retrieval_smoke.py -q

It exists to protect the central claim of the project: a question asked in
romanized Hinglish must find a record written in English, and vice versa.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION") != "1",
    reason="set RUN_INTEGRATION=1 to run (downloads the embedding model)",
)

CORPUS = [
    {
        "question": "What is the hostel fee per semester?",
        "question_original": "hostel ki fees kitni hai",
        "answer": "The hostel fee is approximately Rs 12,000 per semester, with mess charges billed separately.",
        "topic": "hostel",
        "source": "whatsapp",
        "ref": "chat Jun 2026",
        "confidence": 0.9,
    },
    {
        "question": "How are the placements for CSE?",
        "question_original": "cse ka placement kaisa hai",
        "answer": "CSE placements are the strongest on campus, with most of the batch placed and a median package in the double digits in lakhs.",
        "topic": "placements",
        "source": "reddit_thread",
        "ref": "https://reddit.com/r/iiests/x",
        "confidence": 0.8,
    },
    {
        "question": "Can I change my branch after the first year?",
        "question_original": "branch change ho sakta hai first year ke baad",
        "answer": "Branch change is possible after the first year based on your CGPA and the seats available in the target department.",
        "topic": "academics",
        "source": "reddit_wiki",
        "ref": "https://reddit.com/r/iiests/wiki/faq",
        "confidence": 0.95,
    },
    {
        "question": "Is there a night canteen on campus?",
        "question_original": "night canteen hai kya",
        "answer": "Yes, there is a night canteen near the hostels that stays open late.",
        "topic": "campus",
        "source": "whatsapp",
        "ref": "chat Jul 2026",
        "confidence": 0.7,
    },
]


@pytest.fixture(scope="module")
def index():
    from automod.index import store

    return store.build(CORPUS)


@pytest.mark.parametrize(
    "query,expected_question_start",
    [
        # Hinglish in -> English record out. This is the whole point.
        ("hostel fees kitni hai bhai", "What is the hostel fee"),
        ("hostel ki fees kitna lagta hai", "What is the hostel fee"),
        # English in -> same record.
        ("What does the hostel cost each semester?", "What is the hostel fee"),
        # Devanagari in.
        ("हॉस्टल की फीस कितनी है", "What is the hostel fee"),
        # Other topics, both scripts.
        ("cse me placement kaisa hai", "How are the placements"),
        ("can i switch branches after 1st year", "Can I change my branch"),
    ],
)
def test_finds_the_right_record(index, query, expected_question_start):
    from automod.index import store
    from automod.retrieve import _rrf_fuse

    dense = index.dense_search(store.embed_query(query), 4)
    lexical = index.lexical_search(query, 4)
    fused = _rrf_fuse([dense, lexical], 60)
    best = max(fused.items(), key=lambda kv: kv[1])[0]

    assert index.records[best].question.startswith(expected_question_start), (
        f"{query!r} -> {index.records[best].question!r}"
    )


def test_index_round_trips_to_disk(index, tmp_path):
    from automod.index.store import Index

    index.save(tmp_path)
    loaded = Index.load(tmp_path)

    assert len(loaded) == len(index)
    assert loaded.records[0].question == index.records[0].question
    assert loaded.vectors.shape == index.vectors.shape
    assert loaded.lexical_search("hostel fees", 3)
