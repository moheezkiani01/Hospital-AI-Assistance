"""
conversation_manager.py

Explicit state machine for multi-turn flows (booking / reschedule / cancel),
replacing the part-conversational-part-rule-based control flow that used to
live entirely inside chat_service.py's per-flow handler functions (~550 lines
of hand-written nested conditionals per flow).

Design goals, directly from the requested diagram:

    START -> Booking -> Waiting Doctor -> Waiting Date -> Waiting Time ->
             Waiting Name -> Waiting Phone -> Confirm -> Booked

  - One engine, three flow definitions (booking/reschedule/cancel) -- adding,
    removing, or reordering a required step is a one-line change to a
    _FLOW_STEPS entry, not a restructure of nested if/else.
  - Pure functions only. Nothing here touches the database or commits
    anything -- given a Flow and the slots already known on a
    ConversationContext, these functions just compute the truth: what state
    should we be in, what's still missing, are we ready to confirm. This
    makes the whole engine trivially unit-testable without a DB session, and
    keeps persistence (context_manager.py's job) separate from logic (this
    file's job).
  - Order-independent by construction: if every slot arrives in one message,
    next_state() jumps straight to CONFIRM. If slots are corrected out of
    order (user changes their mind on the doctor after giving a time), the
    engine re-derives the right state from whatever's actually filled in --
    there's no separate "transition rule" to get out of sync with reality.
"""

from enum import Enum
from typing import List, NamedTuple, Optional

from app.models.conversation_context import ConversationContext


class Flow(str, Enum):
    BOOKING = "booking"
    RESCHEDULE = "reschedule"
    CANCEL = "cancel"


class FlowState(str, Enum):
    # Booking -- matches the requested diagram exactly.
    BOOKING_WAITING_DOCTOR = "booking_waiting_doctor"
    BOOKING_WAITING_DATE = "booking_waiting_date"
    BOOKING_WAITING_TIME = "booking_waiting_time"
    BOOKING_WAITING_NAME = "booking_waiting_name"
    BOOKING_WAITING_PHONE = "booking_waiting_phone"
    BOOKING_CONFIRM = "booking_confirm"
    BOOKING_BOOKED = "booking_booked"

    # Reschedule -- same shape, applied to "which appointment" instead of a
    # fresh doctor pick, per "the same structure should exist for
    # rescheduling and cancellation".
    RESCHEDULE_WAITING_APPOINTMENT = "reschedule_waiting_appointment"
    RESCHEDULE_WAITING_DATE = "reschedule_waiting_date"
    RESCHEDULE_WAITING_TIME = "reschedule_waiting_time"
    RESCHEDULE_CONFIRM = "reschedule_confirm"
    RESCHEDULE_RESCHEDULED = "reschedule_rescheduled"

    # Cancel -- shortest, still explicit rather than ad hoc.
    CANCEL_WAITING_APPOINTMENT = "cancel_waiting_appointment"
    CANCEL_CONFIRM = "cancel_confirm"
    CANCEL_CANCELLED = "cancel_cancelled"


class SlotStep(NamedTuple):
    state: FlowState      # the state we're in *while waiting* for this slot
    slot_name: str         # attribute name on ConversationContext
    label: str              # human label, for "please also send: X" prompts


# Ordered list per flow. The engine reports the state tied to the FIRST empty
# slot it finds; once every slot is filled, it reports that flow's confirm
# state. Reordering priorities or adding a required field is a one-line edit
# here -- nothing else in the engine needs to change.
_FLOW_STEPS = {
    Flow.BOOKING: [
        SlotStep(FlowState.BOOKING_WAITING_DOCTOR, "doctor_id", "doctor"),
        SlotStep(FlowState.BOOKING_WAITING_DATE, "appointment_date", "date"),
        SlotStep(FlowState.BOOKING_WAITING_TIME, "appointment_time", "time"),
        SlotStep(FlowState.BOOKING_WAITING_NAME, "patient_name", "patient name"),
        SlotStep(FlowState.BOOKING_WAITING_PHONE, "patient_phone", "phone number"),
    ],
    Flow.RESCHEDULE: [
        SlotStep(FlowState.RESCHEDULE_WAITING_APPOINTMENT, "appointment_id", "appointment ID or phone number"),
        SlotStep(FlowState.RESCHEDULE_WAITING_DATE, "appointment_date", "new date"),
        SlotStep(FlowState.RESCHEDULE_WAITING_TIME, "appointment_time", "new time"),
    ],
    Flow.CANCEL: [
        SlotStep(FlowState.CANCEL_WAITING_APPOINTMENT, "appointment_id", "appointment ID or phone number"),
    ],
}

_CONFIRM_STATE = {
    Flow.BOOKING: FlowState.BOOKING_CONFIRM,
    Flow.RESCHEDULE: FlowState.RESCHEDULE_CONFIRM,
    Flow.CANCEL: FlowState.CANCEL_CONFIRM,
}

_TERMINAL_STATE = {
    Flow.BOOKING: FlowState.BOOKING_BOOKED,
    Flow.RESCHEDULE: FlowState.RESCHEDULE_RESCHEDULED,
    Flow.CANCEL: FlowState.CANCEL_CANCELLED,
}

# Recognized as "yes, go ahead" while a flow is sitting in its CONFIRM state.
# Deliberately covers English + Roman Urdu + Urdu script, matching the rest
# of the codebase's language handling.
_CONFIRMATION_PHRASES = {
    "yes", "yes please", "confirm", "confirmed", "ok", "okay", "book it",
    "book", "go ahead", "sounds good", "correct", "right", "yep", "yeah",
    "haan", "han", "ji haan", "ji han", "theek hai", "thik hai", "kar dein",
    "kar do", "book kar dein", "book kar do", "confirm kar dein", "sahi hai",
    "\u062c\u06cc \u06c1\u0627\u06ba", "\u0679\u06be\u06cc\u06a9 \u06c1\u06d2",
}


def steps_for(flow: Flow) -> List[SlotStep]:
    return _FLOW_STEPS[flow]


def initial_state(flow: Flow) -> FlowState:
    """The state a brand-new flow instance starts in: waiting for the first
    required slot."""
    return _FLOW_STEPS[flow][0].state


def next_state(flow: Flow, context: ConversationContext) -> FlowState:
    """Given whatever slots are already filled on `context` right now, report
    which state the flow should be in: the state tied to the first empty
    required slot, or that flow's CONFIRM state if every slot is filled.

    This is re-derived from scratch every call on purpose -- it never trusts
    a previously stored flow_state, so a stale or corrupted flow_state can
    never cause a wrong transition. Call context_manager.set_flow_state()
    with this return value to persist it.
    """
    for step in _FLOW_STEPS[flow]:
        if getattr(context, step.slot_name) in (None, ""):
            return step.state

    return _CONFIRM_STATE[flow]


def missing_slots(flow: Flow, context: ConversationContext) -> List[SlotStep]:
    """All not-yet-filled required slots, in order. Useful for asking for
    several missing things in one message (e.g. if date/time both arrived
    prefilled from memory but name+phone are still needed) instead of always
    asking one at a time."""
    return [
        step
        for step in _FLOW_STEPS[flow]
        if getattr(context, step.slot_name) in (None, "")
    ]


def is_ready_to_confirm(flow: Flow, context: ConversationContext) -> bool:
    return len(missing_slots(flow, context)) == 0


def confirm_state(flow: Flow) -> FlowState:
    return _CONFIRM_STATE[flow]


def terminal_state(flow: Flow) -> FlowState:
    return _TERMINAL_STATE[flow]


def is_confirmation_message(message: str) -> bool:
    """Detect an affirmative 'go ahead' while sitting in a CONFIRM state.
    Deliberately simple/explicit (a lookup, not a model call) because a
    false positive here means booking something the patient didn't actually
    confirm -- that's worth keeping easy to audit and extend by hand."""
    if not message:
        return False

    normalized = message.strip().lower().strip(".!? ")
    return normalized in _CONFIRMATION_PHRASES


def resolve_flow_for_intent(intent: str) -> Optional[Flow]:
    """Map a recognized top-level intent string to a Flow. Returns None for
    intents that aren't one of the three multi-turn flows (FAQ, greeting,
    health question, etc. all fall through to None)."""
    mapping = {
        "book_appointment": Flow.BOOKING,
        "reschedule_appointment": Flow.RESCHEDULE,
        "cancel_appointment": Flow.CANCEL,
    }
    return mapping.get(intent)
