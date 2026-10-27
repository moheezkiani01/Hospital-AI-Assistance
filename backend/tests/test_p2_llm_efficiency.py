from app.services import brain_service, llm_service, tool_router_service


def test_final_reply_prompt_is_bounded_and_uses_no_real_api(monkeypatch):
    captured = {}

    def fake_call(prompt):
        captured["prompt"] = prompt
        return "Theek hai, appointment details verified hain."

    monkeypatch.setattr(llm_service, "call_brain_ai", fake_call)

    answer = brain_service.compose_patient_reply(
        user_message="theek hai",
        authoritative_result="Verified result. " + ("R" * 10000),
        intent="doctor_information",
        recent_chat="old chat " * 2000,
        active_workflow={"mode": "booking", "step": "waiting_for_time"},
        appointment_draft_text="draft " * 1000,
        source_notes="source " * 1000,
    )

    assert answer
    assert len(captured["prompt"]) < 11000
    assert "Final reply only" in captured["prompt"]


def test_native_router_keeps_weekday_semantics_without_real_api(monkeypatch):
    captured = {}

    def fake_tool(prompt, declarations):
        captured["prompt"] = prompt
        captured["tool_count"] = len(declarations)
        return {
            "name": "book_appointment",
            "args": {
                "doctor_name": "Dr Ali",
                "requested_weekday": "Monday",
                "workflow_action": "select_date",
                "language_style": "roman_urdu",
            },
        }

    monkeypatch.setattr(llm_service, "call_brain_tool", fake_tool)

    result = tool_router_service.route_turn(
        user_message="monday ko krdo",
        hospital_name="Test Hospital",
        source="website",
        whatsapp_number=None,
        active_workflow={"mode": "booking", "step": "waiting_for_date"},
        appointment_draft_text="doctor=Dr Ali\n" + ("x" * 5000),
        recent_chat="chat " * 2000,
        recent_appointment_context="none",
    )

    assert result["intent"] == "book_appointment"
    assert result["requested_weekday"] == "Monday"
    assert result["date_was_mentioned"] is True
    assert len(captured["prompt"]) < 6000
