from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String

from app.db.base_class import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=True)

    full_name = Column(String(150), nullable=False)
    email = Column(String(150), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)

    role = Column(String(50), nullable=False, default="receptionist")
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)