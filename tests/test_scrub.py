"""PII scrubbing. The repo is public and the chat is 284 real people."""

from automod.curate.scrub import find_leaks, scrub_record, scrub_text


def test_redacts_indian_phone_numbers():
    for raw in (
        "call me on +91 91442 46933",
        "9144246933 is my number",
        "+919144246933",
        "91442-46933",
    ):
        assert "[phone]" in scrub_text(raw), raw
        assert "46933" not in scrub_text(raw), raw


def test_redacts_emails_and_handles():
    assert scrub_text("mail me at foo.bar@iiests.ac.in") == "mail me at [email]"
    assert "[handle]" in scrub_text("dm @some_student for details")


def test_redacts_group_invites():
    assert "[group-invite]" in scrub_text("join https://chat.whatsapp.com/AbCdEf123")


def test_keeps_legitimate_numbers():
    """Fees, years, ranks and marks must survive — they are the answers."""
    for raw in (
        "The hostel fee is around Rs 12,000 per semester.",
        "Cutoff rank was 45000 in 2024.",
        "You need 75% in boards.",
        "CGPA above 8.5 helps.",
    ):
        assert scrub_text(raw) == raw, raw


def test_scrub_record_covers_all_text_fields():
    record = {
        "question": "kiska number hai 9144246933",
        "question_original": "kiska number hai 9144246933",
        "answer": "mail foo@bar.com",
        "confidence": 0.9,
    }
    cleaned = scrub_record(record)
    assert "9144246933" not in cleaned["question"]
    assert "9144246933" not in cleaned["question_original"]
    assert "[email]" in cleaned["answer"]
    assert cleaned["confidence"] == 0.9


def test_find_leaks_flags_and_clears():
    dirty = "reach me at a@b.com or 9144246933"
    assert find_leaks(dirty)
    assert not find_leaks(scrub_text(dirty))
