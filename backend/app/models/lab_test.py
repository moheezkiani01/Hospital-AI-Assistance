from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text

from app.db.base_class import Base


class LabTest(Base):
    __tablename__ = "lab_tests"

    id = Column(Integer, primary_key=True, index=True)

    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)

    name = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)

    price = Column(Float, nullable=True)
    sample_type = Column(String(100), nullable=True)
    report_time = Column(String(100), nullable=True)

    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)