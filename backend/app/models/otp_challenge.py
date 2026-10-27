from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.db.base_class import Base


class OTPChallenge(Base):
    __tablename__ = "otp_challenges"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, nullable=False, index=True)
    session_id = Column(String(150), nullable=True, index=True)
    appointment_id = Column(Integer, nullable=True, index=True)

    phone = Column(String(50), nullable=False, index=True)
    purpose = Column(String(80), nullable=False, index=True)

    code_hash = Column(String(128), nullable=False)
    verification_token_hash = Column(String(128), nullable=True, index=True)

    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=5)
    is_verified = Column(Boolean, nullable=False, default=False)

    expires_at = Column(DateTime, nullable=False, index=True)
    verified_at = Column(DateTime, nullable=True)
    token_expires_at = Column(DateTime, nullable=True)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
