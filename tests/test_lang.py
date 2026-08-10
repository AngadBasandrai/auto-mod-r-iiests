"""Offline language detection. No network, no API key needed."""

import pytest

from automod.lang import detect


@pytest.mark.parametrize(
    "text",
    [
        "hostel fees kitni hai bhai",
        "placements kaise hai yaar",
        "admission ke liye kya chahiye",
        "mujhe pata nahi ki kaise apply karna hai",
    ],
)
def test_hinglish_detected(text):
    assert detect(text).lang == "hinglish"
    assert detect(text).is_transliterated


@pytest.mark.parametrize(
    "text",
    [
        "What is the hostel fee per semester?",
        "How are the placements for CSE?",
        "Can I change my branch after first year?",
    ],
)
def test_english_detected(text):
    assert detect(text).lang == "en"


def test_devanagari_detected():
    d = detect("हॉस्टल की फीस कितनी है?")
    assert d.lang == "hi"
    assert d.script == "deva"


def test_single_marker_is_not_enough():
    """'bhai' in an otherwise English post should not force a Hinglish reply."""
    assert detect("bhai does anyone know the placement statistics for ECE?").lang == "en"


def test_reply_style_is_defined_for_every_language():
    for text in ("hostel fees kitni hai", "What is the fee?", "फीस कितनी है"):
        assert detect(text).reply_style


def test_empty_text_is_safe():
    assert detect("").lang == "en"


# --- normalizer substitution guard -------------------------------------------
from automod.lang import _looks_substituted  # noqa: E402


def test_detects_a_substituted_question():
    # The real failure: a vague request came back as a specific unrelated one.
    assert _looks_substituted(
        "give a summary of faqs asked regarding iiest",
        "What is the average package offered to CSE students in IIEST?",
        detect("give a summary of faqs asked regarding iiest"),
    )


def test_accepts_a_faithful_restatement():
    assert not _looks_substituted(
        "hostel fees kitni hai",
        "What are the hostel fees?",
        detect("hostel fees kitni hai"),
    )


def test_accepts_a_light_rewording():
    assert not _looks_substituted(
        "how are placements for mechanical",
        "What are the placements like for mechanical engineering students?",
        detect("how are placements for mechanical"),
    )


def test_devanagari_translation_is_never_flagged():
    # Correct translation shares no Latin words with its source.
    original = "छात्रावास का शुल्क कितना है?"
    assert not _looks_substituted(original, "What is the hostel fee?", detect(original))


def test_empty_input_is_not_flagged():
    assert not _looks_substituted("", "What is the hostel fee?", detect(""))
