from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint

from app.db.base_class import Base


class RAGPassage(Base):
    """
    Derived semantic retrieval unit.

    The original Document / DocumentChunk tables remain the source of truth.
    This table is a rebuildable search index: passages are always constructed
    from original document text, while titles/embeddings are retrieval metadata.
    """
    __tablename__ = "rag_passages"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, nullable=False, index=True)
    document_id = Column(Integer, nullable=False, index=True)

    passage_index = Column(Integer, nullable=False)
    source_chunk_start_id = Column(Integer, nullable=True, index=True)
    source_chunk_end_id = Column(Integer, nullable=True, index=True)

    semantic_title = Column(String(300), nullable=True)
    content = Column(Text, nullable=False)

    # Hash of all original source chunks used to build the document index.
    # If document text changes, the derived passages are rebuilt.
    source_hash = Column(String(64), nullable=False, index=True)
    content_hash = Column(String(64), nullable=False, index=True)

    embedding_model = Column(String(120), nullable=True, index=True)
    embedding_dim = Column(Integer, nullable=True)
    embedding_json = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "hospital_id",
            "document_id",
            "passage_index",
            name="uq_rag_passage_document_index",
        ),
    )
