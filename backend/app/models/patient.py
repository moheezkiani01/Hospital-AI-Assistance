from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.db.base_class import Base


class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)

    name = Column(String(150), nullable=False)
    phone = Column(String(50), nullable=False, index=True)
    email = Column(String(150), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    hospital = relationship("Hospital", back_populates="patients")
    appointments = relationship("Appointment", back_populates="patient")