from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.orm import relationship

from app.db.base_class import Base


class Hospital(Base):
    __tablename__ = "hospitals"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), unique=True, nullable=False, index=True)
    address = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    email = Column(String(150), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    doctors = relationship("Doctor", back_populates="hospital")
    patients = relationship("Patient", back_populates="hospital")
    schedules = relationship("Schedule", back_populates="hospital")
    appointments = relationship("Appointment", back_populates="hospital")