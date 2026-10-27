from datetime import date, time, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services import chat_service


def test_new_booking_flow_never_calls_implicit_reschedule(monkeypatch):
    draft = SimpleNamespace(
        hospital_id=1,
        session_id="s1",
        source="website",
        whatsapp_number=None,
        doctor_id=1,
        doctor_name_text="Dr. Test",
        # Always in the future, so the test does not rot when the calendar moves on.
        appointment_date=date.today() + timedelta(days=7),
        appointment_time=time(17, 0),
        patient_name="Patient Test",
        patient_phone="03001234567",
        status="collecting",
    )
    doctor = SimpleNamespace(id=1, name="Dr. Test", specialization="Medicine")

    monkeypatch.setattr(chat_service, "get_or_create_appointment_draft", lambda **kwargs: draft)
    monkeypatch.setattr(chat_service, "build_appointment_context", lambda **kwargs: "")
    monkeypatch.setattr(
        chat_service,
        "ai_understanding_to_appointment_extraction",
        lambda understanding, message: {},
    )
    monkeypatch.setattr(
        chat_service,
        "apply_ai_extraction_to_draft",
        lambda **kwargs: (doctor, []),
    )
    monkeypatch.setattr(chat_service, "get_doctor_by_id", lambda **kwargs: doctor)
    monkeypatch.setattr(
        chat_service,
        "build_slots_for_selected_doctor",
        # The booking flow compares against HH:MM:SS strings (see time_to_slot_string).
        lambda **kwargs: ("Verified live slots", ["17:00:00"]),
    )
    monkeypatch.setattr(chat_service, "get_missing_booking_fields", lambda draft: [])
    monkeypatch.setattr(
        chat_service,
        "find_exact_active_appointment_for_draft",
        lambda db, draft: None,
    )

    # If the old bug ever returns, this test fails immediately.
    monkeypatch.setattr(
        chat_service,
        "try_reschedule_existing_appointment_from_draft",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("NEW booking attempted implicit reschedule")
        ),
    )

    booked = {"called": 0}

    def fake_book(**kwargs):
        booked["called"] += 1
        return {
            "appointment_id": 99,
            "doctor_name": "Dr. Test",
            "status": "booked",
        }

    monkeypatch.setattr(chat_service, "book_appointment_from_draft", fake_book)
    monkeypatch.setattr(
        chat_service,
        "make_ai_reply",
        lambda **kwargs: kwargs["base_instruction"],
    )
    monkeypatch.setattr(
        chat_service,
        "build_chat_response",
        lambda **kwargs: {
            "intent": kwargs["intent"],
            "answer": kwargs["answer"],
        },
    )

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    request = SimpleNamespace(
        hospital_id=1,
        message="new appointment",
        source="website",
        whatsapp_number=None,
    )
    hospital = SimpleNamespace(id=1, name="Test Hospital")

    result = chat_service.handle_appointment_booking_flow(
        db=db,
        request_data=request,
        hospital=hospital,
        session_id="s1",
        chat_history="",
        ai_understanding={"intent": "book_appointment"},
    )

    assert booked["called"] == 1
    assert result["intent"] == "appointment_confirmed"
    assert "Appointment ID: 99" in result["answer"]


def test_explicit_new_booking_overrides_stale_reschedule_state(monkeypatch):
    hospital = SimpleNamespace(id=1, name="Test Hospital")
    request = SimpleNamespace(
        hospital_id=1,
        message="I want a new appointment",
        session_id="s1",
        source="website",
    )

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = hospital

    monkeypatch.setattr(chat_service, "get_recent_chat_history", lambda **kwargs: "")
    monkeypatch.setattr(
        chat_service,
        "get_ai_message_understanding",
        lambda **kwargs: {
            "intent": "book_appointment",
            "confidence": 0.99,
            "_brain_available": True,
            "is_side_question": False,
        },
    )
    monkeypatch.setattr(
        chat_service,
        "get_conversation_state",
        lambda **kwargs: {
            "mode": "reschedule",
            "step": "waiting_for_phone",
            "appointment_id": 16,
        },
    )
    monkeypatch.setattr(chat_service, "get_active_appointment_draft", lambda **kwargs: None)

    cleared = {"called": 0}
    monkeypatch.setattr(
        chat_service,
        "clear_conversation_state",
        lambda *args, **kwargs: cleared.__setitem__("called", cleared["called"] + 1),
    )
    monkeypatch.setattr(
        chat_service,
        "handle_appointment_booking_flow",
        lambda **kwargs: {"intent": "appointment_start", "answer": "new booking started"},
    )

    result = chat_service._handle_chat_message_impl(db, request)

    assert cleared["called"] == 1
    assert result["intent"] == "appointment_start"


def test_llm_phone_value_is_backend_validated(monkeypatch):
    draft = SimpleNamespace(
        hospital_id=1,
        source="website",
        whatsapp_number=None,
        doctor_id=None,
        doctor_name_text=None,
        appointment_date=None,
        appointment_time=None,
        patient_name=None,
        patient_phone=None,
    )

    monkeypatch.setattr(chat_service, "save_draft", lambda db, draft: draft)

    chat_service.apply_ai_extraction_to_draft(
        db=object(),
        draft=draft,
        extraction={"patient_phone": "09876"},
    )

    assert draft.patient_phone is None

    chat_service.apply_ai_extraction_to_draft(
        db=object(),
        draft=draft,
        extraction={"patient_phone": "03001234567"},
    )

    assert draft.patient_phone == "03001234567"
