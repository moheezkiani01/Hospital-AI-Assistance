import hashlib
import json
import re
from typing import Iterable, Optional

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.rag_query_log import RAGQueryLog


def _query_hash(question: str) -> str:
    return hashlib.sha256(str(question or "").encode("utf-8")).hexdigest()


def _safe_preview(question: str) -> Optional[str]:
    if not bool(getattr(settings, "RAG_STORE_SANITIZED_QUERY_PREVIEW", True)):
        return None

    value = str(question or "").strip()
    if not value:
        return None

    # Generic PII minimization. No language vocabulary is used.
    value = re.sub(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        "<email>",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"(?<!\d)\+?\d[\d\s().-]{5,}\d(?!\d)", "<number>", value)
    value = re.sub(r"\s+", " ", value).strip()

    max_chars = int(
        getattr(settings, "RAG_QUERY_PREVIEW_MAX_CHARS", 300) or 300
    )
    return value[:max_chars] or None


def record_query(
    *,
    hospital_id: int,
    question: str,
    retrieval_mode: str,
    evidence: Iterable[dict],
    latency_ms: int,
    second_chance_used: bool = False,
    semantic_rewrite_used: bool = False,
):
    """
    Best-effort telemetry in a separate DB session so retrieval itself never
    succeeds/fails based on analytics logging.
    """
    rows = list(evidence or [])
    embedding_scores = [
        float(item["embedding_score"])
        for item in rows
        if item.get("embedding_score") is not None
    ]
    rerank_scores = [
        float(item["rerank_score"])
        for item in rows
        if item.get("rerank_score") is not None
    ]
    document_ids = sorted({
        int(item["document_id"])
        for item in rows
        if item.get("document_id") is not None
    })

    log = RAGQueryLog(
        hospital_id=int(hospital_id),
        query_hash=_query_hash(question),
        query_preview=_safe_preview(question),
        retrieval_mode=str(retrieval_mode or "unknown")[:50],
        answerable=bool(rows),
        selected_count=len(rows),
        top_embedding_score=max(embedding_scores) if embedding_scores else None,
        top_rerank_score=max(rerank_scores) if rerank_scores else None,
        second_chance_used=bool(second_chance_used),
        semantic_rewrite_used=bool(semantic_rewrite_used),
        latency_ms=max(0, int(latency_ms or 0)),
        document_ids_json=json.dumps(document_ids, separators=(",", ":")),
    )

    db = SessionLocal()
    try:
        db.add(log)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
