from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text

from app.db.base_class import Base


class RAGQueryLog(Base):
    """
    Operational retrieval telemetry.

    Raw prompts/source passages are not stored. query_preview is sanitized and
    can be disabled in config. This table is for retrieval quality monitoring,
    not for storing patient medical records.
    """
    __tablename__ = "rag_query_logs"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, nullable=False, index=True)

    query_hash = Column(String(64), nullable=False, index=True)
    query_preview = Column(Text, nullable=True)

    retrieval_mode = Column(String(50), nullable=False, index=True)
    answerable = Column(Boolean, nullable=False, default=False, index=True)
    selected_count = Column(Integer, nullable=False, default=0)

    top_embedding_score = Column(Float, nullable=True)
    top_rerank_score = Column(Float, nullable=True)

    second_chance_used = Column(Boolean, nullable=False, default=False, index=True)
    semantic_rewrite_used = Column(Boolean, nullable=False, default=False, index=True)

    latency_ms = Column(Integer, nullable=True, index=True)
    document_ids_json = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
