from datetime import datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Time
from sqlalchemy.orm import relationship

from app.db.base_class import Base


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)

    appointment_date = Column(Date, nullable=False)
    appointment_time = Column(Time, nullable=False)
    status = Column(String(30), default="booked")
    reason = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    hospital = relationship("Hospital", back_populates="appointments")
    doctor = relationship("Doctor", back_populates="appointments")
    patient = relationship("Patient", back_populates="appointments")