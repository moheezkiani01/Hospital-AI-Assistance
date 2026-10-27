from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from app.db.base_class import Base


class PatientChatMemory(Base):
    __tablename__ = "patient_chat_memories"

    id = Column(Integer, primary_key=True, index=True)

    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False, index=True)

    # Website session_id or WhatsApp number based session_id
    # Example: web_12345 or whatsapp_923001234567
    session_id = Column(String(150), nullable=False, index=True)

    phone_number = Column(String(50), nullable=True, index=True)
    patient_name = Column(String(150), nullable=True)
    preferred_language = Column(String(50), nullable=True)

    last_appointment_summary = Column(Text, nullable=True)
    last_tests_summary = Column(Text, nullable=True)

    # This stores only info patient clearly asks to save/remember
    saved_information = Column(Text, nullable=True)

    # Short safe memory used by AI
    memory_summary = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("hospital_id", "session_id", name="uq_patient_memory_hospital_session"),
    )