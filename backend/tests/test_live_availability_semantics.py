from types import SimpleNamespace

from app.services import chat_service


def test_specific_doctor_weekly_view_never_exposes_schedule_as_live_slots(monkeypatch):
    doctor = SimpleNamespace(id=7, name="Dr. Test", specialization="Medicine")

    monkeypatch.setattr(
        chat_service,
        "resolve_availability_date",
        lambda message, ai_understanding: None,
    )
    monkeypatch.setattr(
        chat_service,
        "match_doctor",
        lambda **kwargs: (doctor, []),
    )
    monkeypatch.setattr(
        chat_service,
        "build_single_doctor_weekly_context",
        lambda **kwargs: "Monday 5:00 PM to 9:00 PM",
    )
    monkeypatch.setattr(
        chat_service,
        "build_next_available_slots_for_doctor",
        lambda **kwargs: "Next available slots:\\nMonday 6:30 PM\\nMonday 7:30 PM",
    )
    monkeypatch.setattr(
        chat_service,
        "build_chat_response",
        lambda **kwargs: {
            "answer": kwargs["answer"],
            "intent": kwargs["intent"],
        },
    )

    request = SimpleNamespace(
        hospital_id=1,
        message="arbitrary patient wording",
    )
    hospital = SimpleNamespace(id=1, name="Test Hospital")

    result = chat_service.handle_ai_availability_only_flow(
        db=object(),
        request_data=request,
        hospital=hospital,
        session_id="s1",
        chat_history="",
        ai_understanding={
            "intent": "doctor_availability",
            "availability_scope": "specific_doctor",
            "requested_view": "weekly_timings",
            "doctor_id": 7,
            "doctor_name": "Dr. Test",
        },
    )

    answer = result["answer"]

    assert "reference only" in answer
    assert "NOT a list of free appointment slots" in answer
    assert "Live bookable appointment slots" in answer
    assert "Monday 6:30 PM" in answer
    assert "Monday 7:30 PM" in answer


def test_specific_doctor_no_date_defaults_to_live_slots(monkeypatch):
    doctor = SimpleNamespace(id=7, name="Dr. Test", specialization="Medicine")

    monkeypatch.setattr(
        chat_service,
        "resolve_availability_date",
        lambda message, ai_understanding: None,
    )
    monkeypatch.setattr(
        chat_service,
        "match_doctor",
        lambda **kwargs: (doctor, []),
    )
    monkeypatch.setattr(
        chat_service,
        "build_next_available_slots_for_doctor",
        lambda **kwargs: "Next available slots:\\nTuesday 5:30 PM",
    )
    monkeypatch.setattr(
        chat_service,
        "build_chat_response",
        lambda **kwargs: {
            "answer": kwargs["answer"],
            "intent": kwargs["intent"],
        },
    )

    request = SimpleNamespace(hospital_id=1, message="anything")
    hospital = SimpleNamespace(id=1, name="Test Hospital")

    result = chat_service.handle_ai_availability_only_flow(
        db=object(),
        request_data=request,
        hospital=hospital,
        session_id="s1",
        chat_history="",
        ai_understanding={
            "intent": "doctor_availability",
            "availability_scope": "specific_doctor",
            "requested_view": "unknown",
            "doctor_id": 7,
            "doctor_name": "Dr. Test",
        },
    )

    assert "Tuesday 5:30 PM" in result["answer"]
    assert result["intent"] == "doctor_availability_next_slots"
