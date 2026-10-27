import json
import time
from pathlib import Path
from time import perf_counter
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from app.models.rag_passage import RAGPassage
from app.services import rag_embedding_service, rag_service


def load_cases(path: str | Path) -> list[dict]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("RAG evaluation file must contain a JSON array.")
    return [item for item in payload if isinstance(item, dict)]


def _contains_expected(evidence: list[dict], expected_any: Iterable[str]) -> bool:
    expected = [
        str(value).casefold().strip()
        for value in (expected_any or [])
        if str(value or "").strip()
    ]
    if not expected:
        return bool(evidence)

    haystack = "\n".join(
        str(item.get("content") or "")
        for item in evidence
    ).casefold()

    return any(value in haystack for value in expected)


def run_embedding_evaluation(
    db: Session,
    *,
    hospital_id: int,
    cases: list[dict],
    top_k: int = 5,
    limit: Optional[int] = None,
) -> dict:
    """
    Measure pure semantic retrieval recall without making ANY generative LLM
    calls. This tells us whether chunking + embeddings can actually locate the
    correct evidence, independently of Gemini quota/reranker availability.
    """
    selected_cases = cases[:limit] if limit else cases
    answerable_cases = [
        case for case in selected_cases
        if bool(case.get("expected_answerable"))
    ]

    passages = (
        db.query(RAGPassage)
        .filter(RAGPassage.hospital_id == hospital_id)
        .order_by(
            RAGPassage.document_id.asc(),
            RAGPassage.passage_index.asc(),
        )
        .all()
    )

    rows = []
    hits = 0
    total_latency = 0

    for case in answerable_cases:
        question = str(case.get("question") or "").strip()
        expected_any = case.get("expected_any") or []

        started = perf_counter()
        vector = rag_embedding_service.embed_query(question)
        if vector:
            candidates = rag_service._embedding_candidates(
                passages,
                vector,
            )[:max(1, int(top_k))]
        else:
            candidates = []
        latency_ms = int((perf_counter() - started) * 1000)
        total_latency += latency_ms

        evidence = [
            {
                "content": item.get("content"),
                "embedding_score": item.get("embedding_score"),
                "passage_id": item.get("id"),
            }
            for item in candidates
        ]
        hit = _contains_expected(evidence, expected_any)
        hits += 1 if hit else 0

        rows.append({
            "id": case.get("id"),
            "question": question,
            "hit_at_k": hit,
            "top_k": top_k,
            "top_scores": [
                item.get("embedding_score")
                for item in candidates
            ],
            "latency_ms": latency_ms,
        })

    total = len(rows)
    return {
        "mode": "embedding",
        "hospital_id": hospital_id,
        "answerable_cases": total,
        "top_k": top_k,
        "retrieval_recall_at_k_percent": round(
            (hits / total) * 100, 2
        ) if total else 0.0,
        "average_latency_ms": round(
            total_latency / total, 2
        ) if total else 0.0,
        "cases": rows,
    }


def run_full_evaluation(
    db: Session,
    *,
    hospital_id: int,
    cases: list[dict],
    limit: Optional[int] = None,
    delay_seconds: float = 0.0,
    provider_retry_wait_seconds: float = 20.0,
    provider_max_retries: int = 3,
) -> dict:
    """
    Measure the production evidence gate without counting temporary provider
    failures (429/5xx/circuit-open) as RAG quality failures.

    Each case:
      embedding -> vector candidates -> ONE reranker call -> evidence gate

    If the reranker is temporarily unavailable, retry the SAME case after a
    configurable wait. If all retries fail, mark the case provider_error and
    exclude it from quality percentages.
    """
    selected_cases = cases[:limit] if limit else cases

    passages = (
        db.query(RAGPassage)
        .filter(RAGPassage.hospital_id == hospital_id)
        .order_by(
            RAGPassage.document_id.asc(),
            RAGPassage.passage_index.asc(),
        )
        .all()
    )

    rows = []
    answerable_total = 0
    answerable_hits = 0
    unsupported_total = 0
    unsupported_rejected = 0
    answerability_correct = 0
    completed_cases = 0
    provider_error_cases = 0
    total_latency = 0

    max_candidates = int(
        getattr(
            rag_service.settings,
            "RAG_RERANK_MAX_CANDIDATES",
            16,
        )
        or 16
    )

    for index, case in enumerate(selected_cases):
        question = str(case.get("question") or "").strip()
        expected_answerable = bool(case.get("expected_answerable"))
        expected_any = case.get("expected_any") or []

        started = perf_counter()
        query_vector = rag_embedding_service.embed_query(question)

        if not query_vector:
            latency_ms = int((perf_counter() - started) * 1000)
            provider_error_cases += 1
            rows.append({
                "id": case.get("id"),
                "question": question,
                "status": "provider_error",
                "provider_error": "embedding_unavailable",
                "expected_answerable": expected_answerable,
                "latency_ms": latency_ms,
            })
            continue

        candidates = rag_service._embedding_candidates(
            passages,
            query_vector,
        )[:max_candidates]

        rerank = None
        attempts = 0
        max_retries = max(0, int(provider_max_retries))

        while attempts <= max_retries:
            attempts += 1
            rerank = rag_service._llm_rerank_once(
                question,
                candidates,
            )

            if rerank is not None:
                break

            if attempts <= max_retries:
                wait_seconds = max(
                    0.0,
                    float(provider_retry_wait_seconds),
                )
                print(
                    f"[RAG EVAL] reranker unavailable for case "
                    f"{case.get('id') or index + 1}; "
                    f"retry {attempts}/{max_retries} "
                    f"after {wait_seconds:.0f}s"
                )
                if wait_seconds:
                    time.sleep(wait_seconds)

        latency_ms = int((perf_counter() - started) * 1000)
        total_latency += latency_ms

        if rerank is None:
            provider_error_cases += 1
            rows.append({
                "id": case.get("id"),
                "question": question,
                "status": "provider_error",
                "provider_error": "reranker_unavailable",
                "provider_attempts": attempts,
                "expected_answerable": expected_answerable,
                "latency_ms": latency_ms,
            })
        else:
            evidence = rag_service._apply_evidence_gate(
                candidates,
                rerank,
                max_results=5,
            )

            evidence_rows = [
                {
                    "content": item.get("content"),
                    "embedding_score": item.get("embedding_score"),
                    "rerank_score": item.get("rerank_score"),
                }
                for item in evidence
            ]

            actual_answerable = bool(evidence_rows)
            answerability_ok = actual_answerable == expected_answerable
            answerability_correct += 1 if answerability_ok else 0
            completed_cases += 1

            evidence_hit = None
            if expected_answerable:
                answerable_total += 1
                evidence_hit = (
                    bool(evidence_rows)
                    and _contains_expected(
                        evidence_rows,
                        expected_any,
                    )
                )
                answerable_hits += 1 if evidence_hit else 0
            else:
                unsupported_total += 1
                unsupported_rejected += 1 if not evidence_rows else 0

            rows.append({
                "id": case.get("id"),
                "question": question,
                "status": "completed",
                "provider_attempts": attempts,
                "expected_answerable": expected_answerable,
                "actual_answerable": actual_answerable,
                "answerability_correct": answerability_ok,
                "evidence_hit": evidence_hit,
                "latency_ms": latency_ms,
                "top_embedding_score": (
                    evidence_rows[0].get("embedding_score")
                    if evidence_rows else None
                ),
                "top_rerank_score": (
                    evidence_rows[0].get("rerank_score")
                    if evidence_rows else None
                ),
            })

        if delay_seconds > 0 and index < len(selected_cases) - 1:
            time.sleep(delay_seconds)

    requested_total = len(rows)

    return {
        "mode": "full",
        "hospital_id": hospital_id,
        "requested_cases": requested_total,
        "completed_cases": completed_cases,
        "provider_error_cases": provider_error_cases,
        "evaluation_complete": provider_error_cases == 0,
        "answerability_accuracy_percent": round(
            (answerability_correct / completed_cases) * 100, 2
        ) if completed_cases else 0.0,
        "retrieval_hit_at_5_percent": round(
            (answerable_hits / answerable_total) * 100, 2
        ) if answerable_total else 0.0,
        "unsupported_rejection_percent": round(
            (unsupported_rejected / unsupported_total) * 100, 2
        ) if unsupported_total else 0.0,
        "average_latency_ms": round(
            total_latency / requested_total, 2
        ) if requested_total else 0.0,
        "delay_seconds_between_cases": delay_seconds,
        "provider_retry_wait_seconds": provider_retry_wait_seconds,
        "provider_max_retries": provider_max_retries,
        "cases": rows,
    }


# Backward-compatible function name.
def run_evaluation(
    db: Session,
    *,
    hospital_id: int,
    cases: list[dict],
    limit: Optional[int] = None,
) -> dict:
    return run_full_evaluation(
        db,
        hospital_id=hospital_id,
        cases=cases,
        limit=limit,
        delay_seconds=0.0,
        provider_retry_wait_seconds=20.0,
        provider_max_retries=3,
    )
