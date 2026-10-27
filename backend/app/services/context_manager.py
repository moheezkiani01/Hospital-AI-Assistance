"""
context_manager.py

Owns all reads/writes to ConversationContext -- the durable memory of "what
flow is this session in, and what do we already know" that chat_service.py
and conversation_manager.py build on.

Why this file exists (see the diagnosis in project notes / chat history):
the previous conversation_states table was updated by re-passing every field
on every call. Any call site that forgot to re-pass an already-known value
silently overwrote it with NULL. The fix here is structural, not a patch:
`update_slots` only ever touches fields the caller explicitly names, using a
sentinel to tell "not provided" apart from "provided as None". There is no
way to accidentally null out a field you didn't mean to touch.

Two independent things are tracked per session (see model docstring):
  1. In-progress slots for whatever flow is currently active.
  2. Long-lived "last mentioned" memory, independent of any flow, used for
     resolving references like "same doctor" / "wohi time" later.
"""

from datetime import date, time, datetime
from typing import Optional, Any, Dict

from sqlalchemy.orm import Session

from app.models.conversation_context import ConversationContext


# Sentinel so update_slots/remember can tell "argument not passed" apart from
# "argument passed as None" (explicit clear). Do not use None as the default.
_UNSET = object()

# Slot name -> matching "last_*" memory field name. Anything not listed here
# (e.g. patient_name/patient_phone, which aren't useful as "same as before"
# references) is simply not mirrored into long-lived memory.
_MEMORY_MIRROR = {
    "doctor_id": "last_doctor_id",
    "doctor_name_text": "last_doctor_name",
    "appointment_date": "last_date",
    "appointment_time": "last_time",
    "appointment_id": "last_appointment_id",
}

IN_PROGRESS_SLOT_FIELDS = [
    "doctor_id",
    "doctor_name_text",
    "department_id",
    "appointment_date",
    "appointment_time",
    "appointment_id",
    "patient_name",
    "patient_phone",
]


def get_active_context(db: Session, hospital_id: int, session_id: str) -> Optional[ConversationContext]:
    """Read-only lookup. Does not create a row. Use this for routing decisions
    ("is there an active flow?") where creating a blank row would be noise."""
    return (
        db.query(ConversationContext)
        .filter(
            ConversationContext.hospital_id == hospital_id,
            ConversationContext.session_id == session_id,
        )
        .first()
    )


def get_or_create_context(db: Session, hospital_id: int, session_id: str) -> ConversationContext:
    context = get_active_context(db, hospital_id, session_id)

    if context:
        return context

    context = ConversationContext(
        hospital_id=hospital_id,
        session_id=session_id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    db.add(context)
    db.commit()
    db.refresh(context)

    return context


def update_slots(
    db: Session,
    context: ConversationContext,
    *,
    mirror_to_memory: bool = True,
    doctor_id: Any = _UNSET,
    doctor_name_text: Any = _UNSET,
    department_id: Any = _UNSET,
    appointment_date: Any = _UNSET,
    appointment_time: Any = _UNSET,
    appointment_id: Any = _UNSET,
    patient_name: Any = _UNSET,
    patient_phone: Any = _UNSET,
) -> ConversationContext:
    """
    Update only the slots explicitly passed. Anything left at the default
    _UNSET sentinel is left completely untouched on the row -- this is the
    behavior the old raw-SQL save_conversation_state did NOT have, and it is
    the fix for the context-loss bug: a caller that only knows about "7 PM"
    this turn cannot accidentally wipe out the doctor_id learned two turns
    ago, because it simply won't pass doctor_id at all.

    To *intentionally* clear a slot (e.g. user says "not that doctor"), pass
    it explicitly as None: update_slots(db, ctx, doctor_id=None).

    By default, any slot that's actually being set (not cleared) is also
    mirrored into the long-lived last_* memory -- pass mirror_to_memory=False
    to skip this (rarely needed; mainly for tests).
    """
    provided: Dict[str, Any] = {}

    for name, value in (
        ("doctor_id", doctor_id),
        ("doctor_name_text", doctor_name_text),
        ("department_id", department_id),
        ("appointment_date", appointment_date),
        ("appointment_time", appointment_time),
        ("appointment_id", appointment_id),
        ("patient_name", patient_name),
        ("patient_phone", patient_phone),
    ):
        if value is not _UNSET:
            provided[name] = value

    for name, value in provided.items():
        setattr(context, name, value)

    if mirror_to_memory:
        memory_updates = {
            _MEMORY_MIRROR[name]: value
            for name, value in provided.items()
            if name in _MEMORY_MIRROR and value is not None
        }
        for name, value in memory_updates.items():
            setattr(context, name, value)

    context.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(context)

    return context


def remember(
    db: Session,
    context: ConversationContext,
    *,
    doctor_id: Any = _UNSET,
    doctor_name: Any = _UNSET,
    specialization: Any = _UNSET,
    appointment_date: Any = _UNSET,
    appointment_time: Any = _UNSET,
    appointment_id: Any = _UNSET,
) -> ConversationContext:
    """Directly update the long-lived 'last mentioned' memory, independent of
    any in-progress flow. Used e.g. when the entity extractor resolves a
    reference from outside an active flow (a plain question that mentions a
    doctor by name, not part of a booking)."""
    field_map = {
        "last_doctor_id": doctor_id,
        "last_doctor_name": doctor_name,
        "last_specialization": specialization,
        "last_date": appointment_date,
        "last_time": appointment_time,
        "last_appointment_id": appointment_id,
    }

    for name, value in field_map.items():
        if value is not _UNSET:
            setattr(context, name, value)

    context.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(context)

    return context


def start_flow(db: Session, context: ConversationContext, flow: str, initial_state: str) -> ConversationContext:
    """Begin a new flow instance. Clears in-progress slots (a fresh booking
    shouldn't inherit stale in-progress values from a previous, unrelated
    booking attempt) but never touches last_* memory -- if the caller wants
    to prefill from "same doctor as before", that's the entity extractor's
    job, done explicitly via update_slots after this call."""
    for field in IN_PROGRESS_SLOT_FIELDS:
        setattr(context, field, None)

    context.active_flow = flow
    context.flow_state = initial_state
    context.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(context)

    return context


def set_flow_state(db: Session, context: ConversationContext, state: str) -> ConversationContext:
    context.flow_state = state
    context.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(context)
    return context


def end_flow(db: Session, context: ConversationContext, remember_slots: bool = True) -> ConversationContext:
    """End whatever flow is active (completed or abandoned). By default the
    collected slots are pushed into last_* memory first -- even an abandoned
    booking's doctor is a reasonable answer to "same doctor" a few turns
    later -- then in-progress slots and flow position are cleared."""
    if remember_slots:
        remember(
            db,
            context,
            doctor_id=context.doctor_id if context.doctor_id is not None else _UNSET,
            doctor_name=context.doctor_name_text if context.doctor_name_text is not None else _UNSET,
            appointment_date=context.appointment_date if context.appointment_date is not None else _UNSET,
            appointment_time=context.appointment_time if context.appointment_time is not None else _UNSET,
            appointment_id=context.appointment_id if context.appointment_id is not None else _UNSET,
        )

    for field in IN_PROGRESS_SLOT_FIELDS:
        setattr(context, field, None)

    context.active_flow = None
    context.flow_state = None
    context.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(context)

    return context


def reset_context(db: Session, hospital_id: int, session_id: str) -> None:
    """Hard reset -- clears everything including long-lived memory. Intended
    for an explicit 'start over' command or admin/test use, not normal flow
    transitions (use end_flow for those)."""
    context = get_active_context(db, hospital_id, session_id)

    if not context:
        return

    db.delete(context)
    db.commit()


def context_to_dict(context: Optional[ConversationContext]) -> Dict[str, Any]:
    """Plain-dict view, handy for building LLM prompts or for tests."""
    if not context:
        return {}

    def _fmt(value):
        if isinstance(value, (date, time, datetime)):
            return str(value)
        return value

    return {
        "active_flow": context.active_flow,
        "flow_state": context.flow_state,
        "doctor_id": context.doctor_id,
        "doctor_name_text": context.doctor_name_text,
        "department_id": context.department_id,
        "appointment_date": _fmt(context.appointment_date),
        "appointment_time": _fmt(context.appointment_time),
        "appointment_id": context.appointment_id,
        "patient_name": context.patient_name,
        "patient_phone": context.patient_phone,
        "last_doctor_id": context.last_doctor_id,
        "last_doctor_name": context.last_doctor_name,
        "last_specialization": context.last_specialization,
        "last_date": _fmt(context.last_date),
        "last_time": _fmt(context.last_time),
        "last_appointment_id": context.last_appointment_id,
        "language_preference": context.language_preference,
    }
