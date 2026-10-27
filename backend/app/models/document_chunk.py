from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text

from app.db.base_class import Base


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True, index=True)

    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)

    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)