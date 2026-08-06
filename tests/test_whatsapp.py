"""Parser tests.

The Android fixture uses U+202F (narrow no-break space) before "pm", which is
what the real r/iiests export actually contains. Using an ordinary space here
would let these tests pass against a file shape that doesn't exist.
"""

from datetime import datetime

from automod.ingest.whatsapp import parse_text

NNBSP = " "

ANDROID = (
    f"17/05/2026, 8:09{NNBSP}pm - abhinaba, ahilan, angad and yash were added\n"
    f"17/05/2026, 8:09{NNBSP}pm - Messages and calls are end-to-end encrypted.\n"
    f"17/05/2026, 8:10{NNBSP}pm - sagnik: hostel fees kitni hai bhai\n"
    f"17/05/2026, 8:11{NNBSP}pm - yash: around 12k per sem\n"
    f"Mess alag se hai\n"
    f"17/05/2026, 8:12{NNBSP}pm - angad: <Media omitted>\n"
    f"17/05/2026, 8:13{NNBSP}pm - angad: check this: https://example.com\n"
    f"18/05/2026, 9:00{NNBSP}am - ahilan: ok\n"
)

IOS = (
    "[17/05/2026, 8:10:15 PM] sagnik: hostel fees kitni hai\n"
    "[17/05/2026, 8:11:02 PM] yash: 12k\n"
    "[17/05/2026, 8:12:00 PM] angad: image omitted\n"
)

TWENTY_FOUR_HOUR = "06/08/26, 14:32 - angad: placements kaise hai\n"


def test_android_basic():
    messages = parse_text(ANDROID)
    texts = [m.text for m in messages]

    assert "hostel fees kitni hai bhai" in texts
    # System notices and media stubs are dropped.
    assert not any("were added" in t for t in texts)
    assert not any("end-to-end encrypted" in t for t in texts)
    assert not any(t == "<Media omitted>" for t in texts)
    assert len(messages) == 4


def test_android_multiline_continuation():
    messages = parse_text(ANDROID)
    reply = next(m for m in messages if m.text.startswith("around 12k"))
    assert reply.text == "around 12k per sem\nMess alag se hai"


def test_android_timestamp_is_day_first_and_pm():
    messages = parse_text(ANDROID)
    assert messages[0].ts == datetime(2026, 5, 17, 20, 10)


def test_colon_in_body_does_not_break_sender():
    messages = parse_text(ANDROID)
    link = next(m for m in messages if "example.com" in m.text)
    assert link.sender == "angad"
    assert link.text == "check this: https://example.com"


def test_ios_format():
    messages = parse_text(IOS)
    assert [m.sender for m in messages] == ["sagnik", "yash"]
    assert messages[0].ts == datetime(2026, 5, 17, 20, 10, 15)


def test_twenty_four_hour_two_digit_year():
    messages = parse_text(TWENTY_FOUR_HOUR)
    assert messages[0].ts == datetime(2026, 8, 6, 14, 32)


def test_messages_are_sorted():
    messages = parse_text(ANDROID)
    assert messages == sorted(messages, key=lambda m: m.ts)


def test_empty_input():
    assert parse_text("") == []
