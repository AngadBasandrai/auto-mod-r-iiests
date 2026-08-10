"""The guards that decide whether a generated answer is allowed out.

Both cases here are real: they come from replaying r/iiests posts through the
pipeline, and both would have been posted.
"""

from automod.answer import is_echo


def test_rejects_the_posters_own_words():
    # Fan art post. Retrieval returned four records about whether IIEST is an
    # NIT; the model ignored them and restated the post.
    question = (
        "Introducing, IIEST-Chan\n\n"
        "Meet IIEST-Chan, an anthropomorphic version of the IIEST clock tower. "
        "Fully hand drawn and shaded. Turns out I can't do shading if my life "
        "depends on it."
    )
    answer = (
        "IIEST-Chan is an anthropomorphic version of the IIEST clock tower, "
        "fully hand drawn and shaded."
    )
    assert is_echo(answer, question)


def test_allows_an_answer_that_adds_facts():
    question = "How many sharing room in 1st year ??"
    answer = (
        "In the 1st year hostels, rooms are typically shared by 4 students. "
        "Note that there might be a few exceptions with 8 people, but 4 is the "
        "major configuration."
    )
    assert not is_echo(answer, question)


def test_allows_an_answer_reusing_the_questions_nouns_with_a_figure():
    question = "What is the hostel fee?"
    answer = "The hostel fee is approximately Rs 27,000 per semester, including mess."
    assert not is_echo(answer, question)


def test_short_answers_are_never_echoes():
    # "Yes, it is mandatory" is legitimately built from the question's words.
    question = "Is hostel mandatory for first years?"
    assert not is_echo("No, hostel is not mandatory.", question)


def test_hinglish_answer_to_a_hinglish_question_is_not_an_echo():
    question = "hostel fees kitni hai"
    answer = "Hostel fees per semester lagbhag Rs 27,000 hai, including mess."
    assert not is_echo(answer, question)


# --- posts with no subject matter --------------------------------------------
from automod.answer import has_topic  # noqa: E402


def test_rejects_a_bare_plea_for_help():
    # Real post: title "URGENT!!!", body "Can anyone help please". It retrieved
    # every corpus row mentioning help and was answered with reassurance.
    assert not has_topic("URGENT!!!\n\nCan anyone help please")
    assert not has_topic("guys plz help urgent")
    assert not has_topic("Need advice, any suggestions? Thanks in advance")


def test_accepts_a_plea_that_names_its_subject():
    assert has_topic("URGENT!!! can anyone help with hostel allotment please")
    assert has_topic("guys plz help, what is the mess fee")


def test_accepts_ordinary_short_questions():
    for question in (
        "Is ragging bad?",
        "hostel fees kitni hai",
        "How many sharing room in 1st year ??",
        "Is attendance strict",
    ):
        assert has_topic(question), question
