from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from app.db.base_class import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)

    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    uploaded_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    file_name = Column(String(255), nullable=False)
    stored_file_name = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    document_type = Column(String(100), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)