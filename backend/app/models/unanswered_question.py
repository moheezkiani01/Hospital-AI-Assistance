from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from app.db.base_class import Base


class UnansweredQuestion(Base):
    __tablename__ = "unanswered_questions"

    id = Column(Integer, primary_key=True, index=True)

    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)

    question = Column(Text, nullable=False)
    suggested_action = Column(Text, nullable=True)

    status = Column(String(50), default="new")
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)