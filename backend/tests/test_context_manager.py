from datetime import date, time

from app.services import context_manager as cm


def test_get_or_create_context_is_idempotent(db_session):
    ctx1 = cm.get_or_create_context(db_session, hospital_id=1, session_id="s1")
    ctx2 = cm.get_or_create_context(db_session, hospital_id=1, session_id="s1")

    assert ctx1.id == ctx2.id
    assert db_session.query(type(ctx1)).count() == 1


def test_get_active_context_does_not_create(db_session):
    assert cm.get_active_context(db_session, hospital_id=1, session_id="missing") is None
    from app.models.conversation_context import ConversationContext
    assert db_session.query(ConversationContext).count() == 0


def test_update_slots_only_touches_fields_explicitly_passed(db_session):
    """This is the direct regression test for the context-loss bug: a call
    that only knows about one new slot must never blank out slots learned on
    earlier turns."""
    ctx = cm.get_or_create_context(db_session, hospital_id=1, session_id="s1")

    cm.update_slots(db_session, ctx, doctor_id=7, doctor_name_text="Dr Ali")
    assert ctx.doctor_id == 7
    assert ctx.doctor_name_text == "Dr Ali"

    # Simulate the next turn: the message was just "Monday", so only
    # appointment_date is known this time. doctor_id must survive untouched.
    cm.update_slots(db_session, ctx, appointment_date=date(2026, 8, 3))
    assert ctx.doctor_id == 7, "doctor_id was wiped by an update that never mentioned it"
    assert ctx.doctor_name_text == "Dr Ali"
    assert ctx.appointment_date == date(2026, 8, 3)

    # And the next turn again: only the time is known.
    cm.update_slots(db_session, ctx, appointment_time=time(19, 0))
    assert ctx.doctor_id == 7
    assert ctx.appointment_date == date(2026, 8, 3)
    assert ctx.appointment_time == time(19, 0)


def test_update_slots_explicit_none_still_clears(db_session):
    ctx = cm.get_or_create_context(db_session, hospital_id=1, session_id="s1")
    cm.update_slots(db_session, ctx, doctor_id=7)
    assert ctx.doctor_id == 7

    cm.update_slots(db_session, ctx, doctor_id=None)
    assert ctx.doctor_id is None


def test_update_slots_mirrors_into_long_lived_memory(db_session):
    ctx = cm.get_or_create_context(db_session, hospital_id=1, session_id="s1")

    cm.update_slots(
        db_session, ctx,
        doctor_id=7, doctor_name_text="Dr Ali",
        appointment_date=date(2026, 8, 3), appointment_time=time(19, 0),
    )

    assert ctx.last_doctor_id == 7
    assert ctx.last_doctor_name == "Dr Ali"
    assert ctx.last_date == date(2026, 8, 3)
    assert ctx.last_time == time(19, 0)


def test_update_slots_can_skip_memory_mirroring(db_session):
    ctx = cm.get_or_create_context(db_session, hospital_id=1, session_id="s1")
    cm.update_slots(db_session, ctx, doctor_id=7, mirror_to_memory=False)
    assert ctx.doctor_id == 7
    assert ctx.last_doctor_id is None


def test_start_flow_clears_in_progress_slots_but_keeps_memory(db_session):
    from app.services.conversation_manager import Flow

    ctx = cm.get_or_create_context(db_session, hospital_id=1, session_id="s1")
    cm.remember(db_session, ctx, doctor_id=3, doctor_name="Dr Khan")
    # mirror_to_memory=False here on purpose: we want an in-progress value
    # that does NOT touch last_doctor_id, to cleanly isolate what start_flow
    # itself does to each group of fields.
    cm.update_slots(db_session, ctx, doctor_id=99, patient_name="Stale Patient", mirror_to_memory=False)

    cm.start_flow(db_session, ctx, Flow.BOOKING.value, "booking_waiting_doctor")

    assert ctx.doctor_id is None
    assert ctx.patient_name is None
    assert ctx.active_flow == "booking"
    assert ctx.flow_state == "booking_waiting_doctor"
    # Long-lived memory from before the new flow started must survive.
    assert ctx.last_doctor_id == 3
    assert ctx.last_doctor_name == "Dr Khan"


def test_end_flow_pushes_slots_to_memory_then_clears(db_session):
    ctx = cm.get_or_create_context(db_session, hospital_id=1, session_id="s1")
    cm.update_slots(
        db_session, ctx,
        doctor_id=7, doctor_name_text="Dr Ali",
        appointment_date=date(2026, 8, 3), appointment_time=time(19, 0),
        appointment_id=55, mirror_to_memory=False,
    )
    ctx.active_flow = "booking"
    ctx.flow_state = "booking_confirm"
    db_session.commit()

    cm.end_flow(db_session, ctx)

    assert ctx.doctor_id is None
    assert ctx.active_flow is None
    assert ctx.flow_state is None
    assert ctx.last_doctor_id == 7
    assert ctx.last_doctor_name == "Dr Ali"
    assert ctx.last_date == date(2026, 8, 3)
    assert ctx.last_time == time(19, 0)
    assert ctx.last_appointment_id == 55


def test_end_flow_without_remembering(db_session):
    ctx = cm.get_or_create_context(db_session, hospital_id=1, session_id="s1")
    cm.update_slots(db_session, ctx, doctor_id=7, mirror_to_memory=False)

    cm.end_flow(db_session, ctx, remember_slots=False)

    assert ctx.doctor_id is None
    assert ctx.last_doctor_id is None


def test_reset_context_deletes_the_row(db_session):
    cm.get_or_create_context(db_session, hospital_id=1, session_id="s1")
    cm.reset_context(db_session, hospital_id=1, session_id="s1")
    assert cm.get_active_context(db_session, hospital_id=1, session_id="s1") is None


def test_reset_context_on_missing_session_is_a_safe_noop(db_session):
    # Should not raise even though nothing exists yet.
    cm.reset_context(db_session, hospital_id=1, session_id="does-not-exist")


def test_context_to_dict_formats_dates_and_times_as_strings(db_session):
    ctx = cm.get_or_create_context(db_session, hospital_id=1, session_id="s1")
    cm.update_slots(db_session, ctx, appointment_date=date(2026, 8, 3), appointment_time=time(19, 0))

    data = cm.context_to_dict(ctx)
    assert data["appointment_date"] == "2026-08-03"
    assert data["appointment_time"] == "19:00:00"


def test_context_to_dict_on_none_returns_empty_dict():
    assert cm.context_to_dict(None) == {}


def test_sessions_are_isolated_by_session_id(db_session):
    ctx_a = cm.get_or_create_context(db_session, hospital_id=1, session_id="patient-a")
    ctx_b = cm.get_or_create_context(db_session, hospital_id=1, session_id="patient-b")

    cm.update_slots(db_session, ctx_a, doctor_id=1)
    cm.update_slots(db_session, ctx_b, doctor_id=2)

    assert cm.get_active_context(db_session, 1, "patient-a").doctor_id == 1
    assert cm.get_active_context(db_session, 1, "patient-b").doctor_id == 2


def test_sessions_are_isolated_by_hospital_id(db_session):
    """Same session_id string could collide across two different hospitals
    (e.g. a shared widget embed) -- must not leak state between them."""
    ctx_h1 = cm.get_or_create_context(db_session, hospital_id=1, session_id="same-session")
    ctx_h2 = cm.get_or_create_context(db_session, hospital_id=2, session_id="same-session")

    assert ctx_h1.id != ctx_h2.id

    cm.update_slots(db_session, ctx_h1, doctor_id=1)
    assert cm.get_active_context(db_session, 2, "same-session").doctor_id is None
