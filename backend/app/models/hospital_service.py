from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from app.db.base_class import Base


class HospitalService(Base):
    __tablename__ = "hospital_services"

    id = Column(Integer, primary_key=True, index=True)

    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)

    name = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)

    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)