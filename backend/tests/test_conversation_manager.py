from datetime import date, time

import pytest

from app.services import context_manager as cm
from app.services import conversation_manager as sm
from app.services.conversation_manager import Flow, FlowState


def test_initial_state_for_each_flow():
    assert sm.initial_state(Flow.BOOKING) == FlowState.BOOKING_WAITING_DOCTOR
    assert sm.initial_state(Flow.RESCHEDULE) == FlowState.RESCHEDULE_WAITING_APPOINTMENT
    assert sm.initial_state(Flow.CANCEL) == FlowState.CANCEL_WAITING_APPOINTMENT


def test_booking_progression_matches_requested_diagram(db_session):
    """START -> Waiting Doctor -> Waiting Date -> Waiting Time -> Waiting Name
    -> Waiting Phone -> Confirm, one slot at a time."""
    ctx = cm.get_or_create_context(db_session, hospital_id=1, session_id="s1")

    assert sm.next_state(Flow.BOOKING, ctx) == FlowState.BOOKING_WAITING_DOCTOR

    cm.update_slots(db_session, ctx, doctor_id=7, doctor_name_text="Dr Ali")
    assert sm.next_state(Flow.BOOKING, ctx) == FlowState.BOOKING_WAITING_DATE

    cm.update_slots(db_session, ctx, appointment_date=date(2026, 8, 3))
    assert sm.next_state(Flow.BOOKING, ctx) == FlowState.BOOKING_WAITING_TIME

    cm.update_slots(db_session, ctx, appointment_time=time(19, 0))
    assert sm.next_state(Flow.BOOKING, ctx) == FlowState.BOOKING_WAITING_NAME

    cm.update_slots(db_session, ctx, patient_name="Ahmed Raza")
    assert sm.next_state(Flow.BOOKING, ctx) == FlowState.BOOKING_WAITING_PHONE

    cm.update_slots(db_session, ctx, patient_phone="03001234567")
    assert sm.next_state(Flow.BOOKING, ctx) == FlowState.BOOKING_CONFIRM
    assert sm.is_ready_to_confirm(Flow.BOOKING, ctx)


def test_booking_jumps_straight_to_confirm_when_all_slots_arrive_together(db_session):
    ctx = cm.get_or_create_context(db_session, hospital_id=1, session_id="s1")
    cm.update_slots(
        db_session, ctx,
        doctor_id=7, appointment_date=date(2026, 8, 3),
        appointment_time=time(19, 0), patient_name="Ahmed Raza",
        patient_phone="03001234567",
    )
    assert sm.next_state(Flow.BOOKING, ctx) == FlowState.BOOKING_CONFIRM


def test_earliest_missing_slot_wins_regardless_of_what_else_is_filled(db_session):
    """If time and phone somehow arrive before a doctor is chosen, the engine
    still asks for the doctor first -- it never skips ahead."""
    ctx = cm.get_or_create_context(db_session, hospital_id=1, session_id="s1")
    cm.update_slots(
        db_session, ctx,
        appointment_time=time(19, 0), patient_phone="03001234567",
    )
    assert sm.next_state(Flow.BOOKING, ctx) == FlowState.BOOKING_WAITING_DOCTOR


def test_missing_slots_lists_everything_still_needed(db_session):
    ctx = cm.get_or_create_context(db_session, hospital_id=1, session_id="s1")
    cm.update_slots(db_session, ctx, doctor_id=7)

    missing = [step.slot_name for step in sm.missing_slots(Flow.BOOKING, ctx)]
    assert missing == ["appointment_date", "appointment_time", "patient_name", "patient_phone"]


def test_reschedule_progression(db_session):
    ctx = cm.get_or_create_context(db_session, hospital_id=1, session_id="s1")

    assert sm.next_state(Flow.RESCHEDULE, ctx) == FlowState.RESCHEDULE_WAITING_APPOINTMENT

    cm.update_slots(db_session, ctx, appointment_id=42)
    assert sm.next_state(Flow.RESCHEDULE, ctx) == FlowState.RESCHEDULE_WAITING_DATE

    cm.update_slots(db_session, ctx, appointment_date=date(2026, 8, 10))
    assert sm.next_state(Flow.RESCHEDULE, ctx) == FlowState.RESCHEDULE_WAITING_TIME

    cm.update_slots(db_session, ctx, appointment_time=time(11, 0))
    assert sm.next_state(Flow.RESCHEDULE, ctx) == FlowState.RESCHEDULE_CONFIRM


def test_cancel_progression(db_session):
    ctx = cm.get_or_create_context(db_session, hospital_id=1, session_id="s1")

    assert sm.next_state(Flow.CANCEL, ctx) == FlowState.CANCEL_WAITING_APPOINTMENT

    cm.update_slots(db_session, ctx, appointment_id=42)
    assert sm.next_state(Flow.CANCEL, ctx) == FlowState.CANCEL_CONFIRM


@pytest.mark.parametrize(
    "message,expected",
    [
        ("Book it", True),
        ("book", True),
        ("yes", True),
        ("Yes please!", True),
        ("haan", True),
        ("Han ji", False),  # word order not in the phrase list -- see note below
        ("theek hai", True),
        ("confirm kar dein", True),
        ("Monday", False),
        ("7 PM", False),
        ("dr ali please", False),
        ("", False),
        (None, False),
    ],
)
def test_is_confirmation_message(message, expected):
    assert sm.is_confirmation_message(message) is expected


def test_resolve_flow_for_intent():
    assert sm.resolve_flow_for_intent("book_appointment") == Flow.BOOKING
    assert sm.resolve_flow_for_intent("reschedule_appointment") == Flow.RESCHEDULE
    assert sm.resolve_flow_for_intent("cancel_appointment") == Flow.CANCEL
    assert sm.resolve_flow_for_intent("general_question") is None
    assert sm.resolve_flow_for_intent("unknown") is None


def test_exact_bug_report_scenario_doctor_survives_all_four_turns(db_session):
    """
    Reproduces, turn for turn, the scenario from the bug report:

        Show Dr Ali slots -> Monday -> 7 PM -> Book it

    Patient is a recognized returning patient (name/phone already on file,
    e.g. via WhatsApp number), which is why "Book it" is enough on turn 4 --
    matching the original report where only doctor/date/time were discussed.

    The one assertion that would have failed against the old
    confidence-gated routing + raw-overwrite conversation_states table is
    marked below.
    """
    ctx = cm.get_or_create_context(db_session, hospital_id=1, session_id="whatsapp-923001234567")

    # Returning patient recognized up front (e.g. from WhatsApp number lookup).
    cm.update_slots(db_session, ctx, patient_name="Ahmed Raza", patient_phone="03001234567")
    cm.start_flow(db_session, ctx, Flow.BOOKING.value, sm.initial_state(Flow.BOOKING).value)
    # start_flow clears in-progress slots by design -- restore the known patient.
    cm.update_slots(db_session, ctx, patient_name="Ahmed Raza", patient_phone="03001234567")

    # Turn 1: "Show Dr Ali slots"
    cm.update_slots(db_session, ctx, doctor_id=7, doctor_name_text="Dr Ali")
    assert sm.next_state(Flow.BOOKING, ctx) == FlowState.BOOKING_WAITING_DATE

    # Turn 2: "Monday" -- this call knows nothing about the doctor.
    cm.update_slots(db_session, ctx, appointment_date=date(2026, 8, 3))
    assert ctx.doctor_id == 7, "BUG REPRODUCED: doctor was lost after turn 2"
    assert sm.next_state(Flow.BOOKING, ctx) == FlowState.BOOKING_WAITING_TIME

    # Turn 3: "7 PM" -- this call knows nothing about the doctor or the date.
    cm.update_slots(db_session, ctx, appointment_time=time(19, 0))
    assert ctx.doctor_id == 7, "BUG REPRODUCED: doctor was lost after turn 3"
    assert ctx.appointment_date == date(2026, 8, 3), "BUG REPRODUCED: date was lost after turn 3"
    assert sm.next_state(Flow.BOOKING, ctx) == FlowState.BOOKING_CONFIRM

    # Turn 4: "Book it" -- a short confirmation with zero new entities. The
    # old code's confidence-gated routing was the failure point here; this
    # engine doesn't consult any confidence score at all.
    assert sm.is_confirmation_message("Book it")
    assert sm.is_ready_to_confirm(Flow.BOOKING, ctx)
    assert ctx.doctor_id == 7
    assert ctx.doctor_name_text == "Dr Ali"
    assert ctx.appointment_date == date(2026, 8, 3)
    assert ctx.appointment_time == time(19, 0)
    assert ctx.patient_name == "Ahmed Raza"
    assert ctx.patient_phone == "03001234567"
