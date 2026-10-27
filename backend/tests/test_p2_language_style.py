from app.services import brain_service, llm_service


def test_latin_input_rejects_non_latin_reply_without_vocabulary(monkeypatch):
    """
    This test is intentionally vocabulary-free.

    It verifies only the writing-system contract:
    Latin-script patient input must not be answered in Devanagari/Urdu script.
    Semantic language understanding remains the LLM's responsibility.
    """
    replies = iter([
        "यह उत्तर गलत लिपि में है।",
        "Response remains in the patient's Latin writing system.",
    ])
    calls = {"count": 0}

    def fake_call(prompt):
        calls["count"] += 1
        return next(replies)

    monkeypatch.setattr(llm_service, "call_brain_ai", fake_call)

    answer = brain_service.compose_patient_reply(
        user_message="abc xyz?",
        authoritative_result="Verified backend result.",
        intent="information_unconfirmed",
    )

    assert answer
    assert calls["count"] == 2
    assert not any("\u0900" <= ch <= "\u097f" for ch in answer)
    assert not any(
        ("\u0600" <= ch <= "\u06ff")
        or ("\u0750" <= ch <= "\u077f")
        or ("\u08a0" <= ch <= "\u08ff")
        for ch in answer
    )


def test_valid_latin_reply_needs_no_repair(monkeypatch):
    calls = {"count": 0}

    def fake_call(prompt):
        calls["count"] += 1
        return "Valid Latin-script response."

    monkeypatch.setattr(llm_service, "call_brain_ai", fake_call)

    answer = brain_service.compose_patient_reply(
        user_message="abc xyz?",
        authoritative_result="Verified backend result.",
        intent="doctor_information",
    )

    assert answer == "Valid Latin-script response."
    assert calls["count"] == 1


def test_script_detection_is_character_based_not_word_based():
    """
    No Roman-Urdu/Hindi/English vocabulary is required.
    The guard identifies only the visible writing system.
    """
    assert brain_service._preferred_patient_script("abc XYZ 123") == "latin"
    assert brain_service._preferred_patient_script("اردو") == "urdu"
    assert brain_service._preferred_patient_script("हिन्दी") == "devanagari"
