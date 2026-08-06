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
