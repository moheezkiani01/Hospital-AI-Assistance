from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from app.db.base_class import Base


class ChatFeedback(Base):
    __tablename__ = "chat_feedback"

    id = Column(Integer, primary_key=True, index=True)

    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    chat_log_id = Column(Integer, ForeignKey("chat_logs.id"), nullable=True)

    message = Column(Text, nullable=True)
    answer = Column(Text, nullable=True)
    intent = Column(String(100), nullable=True)

    rating = Column(Integer, nullable=True)
    helpful = Column(Boolean, nullable=True)
    comment = Column(Text, nullable=True)

    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)