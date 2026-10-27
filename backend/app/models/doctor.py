from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.db.base_class import Base


class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)

    name = Column(String(150), nullable=False, index=True)
    specialization = Column(String(150), nullable=False)
    consultation_fee = Column(Float, nullable=False, default=0)
    phone = Column(String(50), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    hospital = relationship("Hospital", back_populates="doctors")
    schedules = relationship("Schedule", back_populates="doctor")
    appointments = relationship("Appointment", back_populates="doctor")