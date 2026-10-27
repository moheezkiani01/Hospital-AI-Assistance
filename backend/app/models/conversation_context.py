from datetime import datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Text, Time, UniqueConstraint

from app.db.base_class import Base


class ConversationContext(Base):
    """
    Single source of truth for "where is this session in its conversation, and
    what do we already know".

    This replaces the ad-hoc `conversation_states` raw-SQL table that lived
    inside chat_service.py (used only by reschedule/cancel/status) and gives
    booking the same durable state that reschedule had, plus one thing neither
    flow had: a permanent, flow-independent "last mentioned" memory so
    references like "same doctor" / "wohi time" / "mera wala doctor" keep
    resolving even after a flow finishes, is abandoned, or switches to a
    different flow.

    Two groups of fields, on purpose:

    - active_flow / flow_state / (doctor_id, appointment_date, ...):
      the CURRENT flow's in-progress slots. Cleared when a flow ends.
    - last_doctor_id / last_date / ... :
      "the last thing we talked about", independent of any flow. Never
      cleared by ending a flow -- only overwritten when something new is
      confirmed. This is what makes "book with the same doctor again" work
      five turns after the first booking completed.
    """

    __tablename__ = "conversation_contexts"

    id = Column(Integer, primary_key=True, index=True)

    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False, index=True)
    session_id = Column(String(150), nullable=False, index=True)

    # --- Explicit state machine position (see conversation_manager.FlowState) ---
    active_flow = Column(String(50), nullable=True)   # "booking" | "reschedule" | "cancel" | None
    flow_state = Column(String(50), nullable=True)    # e.g. "waiting_doctor", "confirm"

    # --- In-progress slots for the ACTIVE flow only ---
    doctor_id = Column(Integer, nullable=True)
    doctor_name_text = Column(String(200), nullable=True)
    department_id = Column(Integer, nullable=True)
    appointment_date = Column(Date, nullable=True)
    appointment_time = Column(Time, nullable=True)
    appointment_id = Column(Integer, nullable=True)
    patient_name = Column(String(200), nullable=True)
    patient_phone = Column(String(50), nullable=True)

    # --- Long-lived reference memory (survives flow end/switch) ---
    last_doctor_id = Column(Integer, nullable=True)
    last_doctor_name = Column(String(200), nullable=True)
    last_specialization = Column(String(150), nullable=True)
    last_date = Column(Date, nullable=True)
    last_time = Column(Time, nullable=True)
    last_appointment_id = Column(Integer, nullable=True)

    language_preference = Column(String(20), nullable=True)  # "en" | "roman_ur" | "ur"

    # Small free-form bag for anything flow-specific that isn't worth a column yet.
    # Treat as internal to context_manager -- everything else should go through
    # named fields above so the merge/clear rules stay predictable.
    extra_json = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("hospital_id", "session_id", name="uq_conversation_context_hospital_session"),
    )
