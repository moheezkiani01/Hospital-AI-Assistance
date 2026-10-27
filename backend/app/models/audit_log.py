from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.db.base_class import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, nullable=True, index=True)

    actor_type = Column(String(50), nullable=False, default="system", index=True)
    actor_user_id = Column(Integer, nullable=True, index=True)
    session_id = Column(String(150), nullable=True, index=True)
    request_id = Column(String(80), nullable=True, index=True)

    action = Column(String(100), nullable=False, index=True)
    entity_type = Column(String(80), nullable=False, index=True)
    entity_id = Column(String(80), nullable=True, index=True)
    outcome = Column(String(30), nullable=False, default="success", index=True)

    changed_fields = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
