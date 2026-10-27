from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from app.db.base_class import Base


class LLMCallLog(Base):
    __tablename__ = "llm_call_logs"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, nullable=True, index=True)
    session_id = Column(String(150), nullable=True, index=True)
    request_id = Column(String(80), nullable=True, index=True)

    provider = Column(String(50), nullable=False, index=True)
    model = Column(String(150), nullable=True, index=True)
    call_type = Column(String(30), nullable=False, default="text", index=True)
    success = Column(Boolean, nullable=False, default=False, index=True)
    fallback_from = Column(String(80), nullable=True)

    latency_ms = Column(Integer, nullable=True)
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    token_count_source = Column(String(30), nullable=True, default="estimated")
    input_chars = Column(Integer, nullable=True)
    output_chars = Column(Integer, nullable=True)

    status_code = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
