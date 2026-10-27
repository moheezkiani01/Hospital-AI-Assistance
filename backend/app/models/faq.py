from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from app.db.base_class import Base


class FAQ(Base):
    __tablename__ = "faqs"

    id = Column(Integer, primary_key=True, index=True)

    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)

    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    category = Column(String(100), nullable=True)

    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)