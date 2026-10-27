from datetime import datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Time
from app.db.base_class import Base


class AppointmentDraft(Base):
    __tablename__ = "appointment_drafts"

    id = Column(Integer, primary_key=True, index=True)

    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False, index=True)
    session_id = Column(String(150), nullable=False, index=True)

    source = Column(String(50), default="website")  # website / whatsapp
    whatsapp_number = Column(String(50), nullable=True)

    doctor_id = Column(Integer, nullable=True)
    doctor_name_text = Column(String(200), nullable=True)

    appointment_date = Column(Date, nullable=True)
    appointment_time = Column(Time, nullable=True)

    patient_name = Column(String(200), nullable=True)
    patient_phone = Column(String(50), nullable=True)

    status = Column(String(50), default="collecting")  # collecting / completed / cancelled

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)