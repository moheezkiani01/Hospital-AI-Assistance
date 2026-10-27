from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from app.db.base_class import Base


class ChatLog(Base):
    __tablename__ = "chat_logs"

    id = Column(Integer, primary_key=True, index=True)

    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False, index=True)

    # Important for separate patient memory
    # For website: browser session id
    # For WhatsApp later: whatsapp phone number/session id
    session_id = Column(String(150), nullable=True, index=True, default="default")

    message = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    intent = Column(String(100), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)