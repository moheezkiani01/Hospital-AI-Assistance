from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from app.db.base_class import Base


class PatientLead(Base):
    __tablename__ = "patient_leads"

    id = Column(Integer, primary_key=True, index=True)

    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)

    name = Column(String(150), nullable=False)
    phone = Column(String(50), nullable=False)
    question = Column(Text, nullable=True)
    interested_service = Column(String(150), nullable=True)

    status = Column(String(50), default="new")
    source = Column(String(100), default="chatbot")

    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)