"""Windowing and pseudonymization."""

from datetime import datetime, timedelta

from automod.curate.sessionize import sessionize
from automod.ingest.whatsapp import Message

BASE = datetime(2026, 5, 17, 20, 0)


def msg(minutes: int, sender: str, text: str) -> Message:
    return Message(ts=BASE + timedelta(minutes=minutes), sender=sender, text=text)


def test_splits_on_long_gap():
    messages = [
        msg(0, "a", "hostel fees kitni hai"),
        msg(1, "b", "12k per sem"),
        msg(500, "a", "placements kaise hai"),
        msg(501, "b", "decent for cse"),
    ]
    windows = sessionize(messages, gap_minutes=45)
    assert len(windows) == 2
    assert len(windows[0].messages) == 2


def test_splits_on_message_cap_with_overlap():
    messages = [msg(i, "a", f"line {i}") for i in range(12)]
    windows = sessionize(messages, gap_minutes=45, max_messages=5, overlap=2)
    assert len(windows) >= 2
    # The overlap must carry the tail of one window into the head of the next.
    assert windows[0].messages[-2:] == windows[1].messages[:2]


def test_real_names_never_reach_the_transcript():
    messages = [
        msg(0, "sagnik bhattacharjee", "hostel fees kitni hai"),
        msg(1, "+91 91442 46933", "12k per sem"),
    ]
    transcript = sessionize(messages)[0].render()
    assert "sagnik" not in transcript
    assert "91442" not in transcript
    assert "User1: hostel fees kitni hai" in transcript
    assert "User2: 12k per sem" in transcript


def test_window_key_is_stable_and_content_addressed():
    messages = [msg(0, "a", "q"), msg(1, "b", "a")]
    first = sessionize(messages)[0]
    second = sessionize(messages)[0]
    assert first.key == second.key

    changed = sessionize([msg(0, "a", "q"), msg(1, "b", "different")])[0]
    assert changed.key != first.key


def test_single_message_windows_are_dropped():
    assert sessionize([msg(0, "a", "hi")]) == []


def test_empty_input():
    assert sessionize([]) == []
