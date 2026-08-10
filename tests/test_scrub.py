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


# --- corpus-level structural filters ----------------------------------------
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

from automod.curate.build_corpus import (  # noqa: E402
    apply_blocklist,
    drop_boilerplate_answers,
    drop_personal_rows,
    load_blocklist,
)


def _row(question: str, answer: str = "some answer text here") -> dict:
    return {"question": question, "answer": answer, "confidence": 0.8}


def test_drops_rows_about_a_person():
    rows = [
        _row("What is the JEE ADV score of User1?", "User1 scored around 80."),
        _row("What is the hostel fee?", "The hostel fee is Rs 12,000."),
        _row("How much RAM does User 4 have?", "16GB."),
    ]
    kept = drop_personal_rows(rows)
    assert len(kept) == 1
    assert kept[0]["question"] == "What is the hostel fee?"


def test_keeps_rows_that_merely_contain_the_word_user():
    # "user" without a number is ordinary English and must survive.
    rows = [_row("Is the wifi good?", "Every user gets a login for the campus wifi.")]
    assert drop_personal_rows(rows) == rows


def test_blocklist_is_case_insensitive_and_spans_question_and_answer():
    rows = [
        _row("How much is the hostel fee?", "The hostel fee is approximately Rs 485."),
        _row("How much is the hostel fee?", "The hostel fee is approximately Rs 12,000."),
    ]
    patterns = [__import__("re").compile(r"rs 485", __import__("re").I)]
    kept = apply_blocklist(rows, patterns)
    assert len(kept) == 1
    assert "12,000" in kept[0]["answer"]


def test_no_blocklist_file_is_not_an_error():
    assert load_blocklist(Path("does") / "not" / "exist.txt") == []


def test_malformed_pattern_is_skipped_not_fatal():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "blocklist.txt"
        path.write_text(
            "# a comment\n\nvalid pattern\n[unclosed\n", encoding="utf-8"
        )
        assert len(load_blocklist(path)) == 1


def test_drops_answers_reused_across_many_questions():
    boilerplate = "A practical index for hostel life, rules and photos."
    rows = [
        _row("What types of rooms are there?", boilerplate),
        _row("How clean are the hostels?", boilerplate),
        _row("What are the hostel rules?", boilerplate),
        _row("What is the mess fee?", "The mess fee is 27.7k."),
    ]
    kept = drop_boilerplate_answers(rows)
    assert len(kept) == 1
    assert "27.7k" in kept[0]["answer"]


def test_keeps_an_answer_repeated_only_twice():
    # Two near-duplicates are dedupe's job, not a boilerplate signal.
    rows = [_row("Q one?", "Same answer text."), _row("Q two?", "Same answer text.")]
    assert len(drop_boilerplate_answers(rows)) == 2
