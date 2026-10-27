from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.database import get_db
from app.models.audit_log import AuditLog
from app.models.llm_call_log import LLMCallLog
from app.models.rag_query_log import RAGQueryLog
from app.models.user import User
from app.services import provider_health_service


router = APIRouter()


def _hospital_scope(current_user: User, requested_hospital_id: Optional[int]):
    if current_user.hospital_id is not None:
        return current_user.hospital_id
    return requested_hospital_id


@router.get("/audit-logs")
def get_audit_logs(
    hospital_id: Optional[int] = Query(default=None),
    entity_type: Optional[str] = Query(default=None),
    action: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin"])),
):
    hospital_id = _hospital_scope(current_user, hospital_id)
    query = db.query(AuditLog)
    if hospital_id is not None:
        query = query.filter(AuditLog.hospital_id == hospital_id)
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if action:
        query = query.filter(AuditLog.action == action)

    rows = query.order_by(AuditLog.created_at.desc()).limit(limit).all()
    return [
        {
            "id": row.id,
            "hospital_id": row.hospital_id,
            "actor_type": row.actor_type,
            "actor_user_id": row.actor_user_id,
            "session_id": row.session_id,
            "request_id": row.request_id,
            "action": row.action,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "outcome": row.outcome,
            "changed_fields": row.changed_fields,
            "metadata_json": row.metadata_json,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.get("/llm-providers")
def get_llm_provider_health(
    current_user: User = Depends(require_roles(["admin"])),
):
    """Providers the circuit breaker is currently skipping (empty = all healthy).

    State is held in memory, so it resets when the API restarts.
    """
    return {"providers_in_cooldown": provider_health_service.snapshot()}


@router.get("/llm-calls")
def get_llm_calls(
    hospital_id: Optional[int] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    success: Optional[bool] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin"])),
):
    hospital_id = _hospital_scope(current_user, hospital_id)
    query = db.query(LLMCallLog)
    if hospital_id is not None:
        query = query.filter(LLMCallLog.hospital_id == hospital_id)
    if provider:
        query = query.filter(LLMCallLog.provider == provider)
    if success is not None:
        query = query.filter(LLMCallLog.success == success)

    rows = query.order_by(LLMCallLog.created_at.desc()).limit(limit).all()
    return [
        {
            "id": row.id,
            "hospital_id": row.hospital_id,
            "session_id": row.session_id,
            "request_id": row.request_id,
            "provider": row.provider,
            "model": row.model,
            "call_type": row.call_type,
            "success": row.success,
            "fallback_from": row.fallback_from,
            "latency_ms": row.latency_ms,
            "prompt_tokens": row.prompt_tokens,
            "completion_tokens": row.completion_tokens,
            "total_tokens": row.total_tokens,
            "token_count_source": row.token_count_source,
            "status_code": row.status_code,
            "error_message": row.error_message,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.get("/llm-summary")
def get_llm_summary(
    hospital_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin"])),
):
    hospital_id = _hospital_scope(current_user, hospital_id)
    query = db.query(LLMCallLog)
    if hospital_id is not None:
        query = query.filter(LLMCallLog.hospital_id == hospital_id)

    total = query.count()
    failures = query.filter(LLMCallLog.success == False).count()
    avg_latency = query.with_entities(func.avg(LLMCallLog.latency_ms)).scalar()
    total_tokens = query.with_entities(func.sum(LLMCallLog.total_tokens)).scalar()

    # Aggregate statuses only. Do not return prompts or patient messages.
    failure_expr = case((LLMCallLog.success.is_(False), 1), else_=0)
    fallback_expr = case((LLMCallLog.fallback_from.isnot(None), 1), else_=0)
    overload_expr = case((LLMCallLog.status_code == 503, 1), else_=0)

    by_provider = (
        query.with_entities(
            LLMCallLog.provider,
            func.count(LLMCallLog.id),
            func.avg(LLMCallLog.latency_ms),
            func.sum(failure_expr),
            func.sum(fallback_expr),
            func.sum(overload_expr),
        )
        .group_by(LLMCallLog.provider)
        .all()
    )

    last_day = query.filter(LLMCallLog.created_at >= datetime.utcnow() - timedelta(hours=24))
    recent_total = last_day.count()
    recent_failed = last_day.filter(LLMCallLog.success.is_(False)).count()

    return {
        "total_calls": total,
        "failed_calls": failures,
        "success_rate": round(((total - failures) / total) * 100, 2) if total else 0.0,
        "average_latency_ms": round(float(avg_latency or 0), 2),
        "estimated_total_tokens": int(total_tokens or 0),
        "recent_24h": {
            "total_calls": recent_total,
            "failed_calls": recent_failed,
            "success_rate": round(((recent_total - recent_failed) / recent_total) * 100, 2)
            if recent_total else 0.0,
        },
        "providers": [
            {
                "provider": provider,
                "calls": count,
                "failed_calls": int(failed or 0),
                "success_rate": round(((count - int(failed or 0)) / count) * 100, 2) if count else 0.0,
                "fallback_calls": int(fallbacks or 0),
                "overload_503_calls": int(overloads or 0),
                "average_latency_ms": round(float(latency or 0), 2),
            }
            for provider, count, latency, failed, fallbacks, overloads in by_provider
        ],
    }



@router.get("/rag-queries")
def get_rag_queries(
    hospital_id: Optional[int] = Query(default=None),
    answerable: Optional[bool] = Query(default=None),
    semantic_rewrite_used: Optional[bool] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin"])),
):
    hospital_id = _hospital_scope(current_user, hospital_id)
    query = db.query(RAGQueryLog)

    if hospital_id is not None:
        query = query.filter(RAGQueryLog.hospital_id == hospital_id)
    if answerable is not None:
        query = query.filter(RAGQueryLog.answerable == answerable)
    if semantic_rewrite_used is not None:
        query = query.filter(
            RAGQueryLog.semantic_rewrite_used == semantic_rewrite_used
        )

    rows = (
        query.order_by(RAGQueryLog.created_at.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "id": row.id,
            "hospital_id": row.hospital_id,
            "query_hash": row.query_hash,
            "query_preview": row.query_preview,
            "retrieval_mode": row.retrieval_mode,
            "answerable": row.answerable,
            "selected_count": row.selected_count,
            "top_embedding_score": row.top_embedding_score,
            "top_rerank_score": row.top_rerank_score,
            "second_chance_used": row.second_chance_used,
            "semantic_rewrite_used": row.semantic_rewrite_used,
            "latency_ms": row.latency_ms,
            "document_ids_json": row.document_ids_json,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.get("/rag-summary")
def get_rag_summary(
    hospital_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin"])),
):
    hospital_id = _hospital_scope(current_user, hospital_id)
    query = db.query(RAGQueryLog)

    if hospital_id is not None:
        query = query.filter(RAGQueryLog.hospital_id == hospital_id)

    total = query.count()
    answerable = query.filter(RAGQueryLog.answerable == True).count()
    no_evidence = total - answerable
    rewrites = query.filter(
        RAGQueryLog.semantic_rewrite_used == True
    ).count()
    second_chance = query.filter(
        RAGQueryLog.second_chance_used == True
    ).count()

    avg_latency = query.with_entities(
        func.avg(RAGQueryLog.latency_ms)
    ).scalar()
    avg_embedding = query.with_entities(
        func.avg(RAGQueryLog.top_embedding_score)
    ).scalar()
    avg_rerank = query.with_entities(
        func.avg(RAGQueryLog.top_rerank_score)
    ).scalar()

    by_mode = (
        query.with_entities(
            RAGQueryLog.retrieval_mode,
            func.count(RAGQueryLog.id),
        )
        .group_by(RAGQueryLog.retrieval_mode)
        .all()
    )

    return {
        "total_queries": total,
        "answerable_queries": answerable,
        "no_evidence_queries": no_evidence,
        "answerable_rate_percent": round(
            (answerable / total) * 100, 2
        ) if total else 0.0,
        "semantic_rewrite_queries": rewrites,
        "semantic_rewrite_rate_percent": round(
            (rewrites / total) * 100, 2
        ) if total else 0.0,
        "second_chance_queries": second_chance,
        "average_latency_ms": round(float(avg_latency or 0), 2),
        "average_top_embedding_score": round(float(avg_embedding or 0), 4),
        "average_top_rerank_score": round(float(avg_rerank or 0), 4),
        "retrieval_modes": [
            {"mode": mode, "queries": count}
            for mode, count in by_mode
        ],
    }
