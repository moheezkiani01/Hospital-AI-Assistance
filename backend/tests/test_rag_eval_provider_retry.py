from types import SimpleNamespace

from app.services import rag_eval_service


def _fake_db_with_passage():
    passage = SimpleNamespace(
        id=1,
        hospital_id=1,
        document_id=1,
        passage_index=0,
        content="Expected evidence.",
        embedding_model="gemini-embedding-2",
        embedding_json="[1.0,0.0]",
    )

    class Query:
        def filter(self, *a, **k):
            return self
        def order_by(self, *a, **k):
            return self
        def all(self):
            return [passage]

    class DB:
        def query(self, *a, **k):
            return Query()

    return DB(), passage


def test_provider_failure_is_not_counted_as_rag_miss(monkeypatch):
    db, passage = _fake_db_with_passage()

    monkeypatch.setattr(
        rag_eval_service.rag_embedding_service,
        "embed_query",
        lambda q: [1.0, 0.0],
    )
    monkeypatch.setattr(
        rag_eval_service.rag_service,
        "_embedding_candidates",
        lambda passages, vector: [{
            "id": 1,
            "passage": passage,
            "title": None,
            "content": "Expected evidence.",
            "embedding_score": 0.99,
        }],
    )
    monkeypatch.setattr(
        rag_eval_service.rag_service,
        "_llm_rerank_once",
        lambda question, candidates: None,
    )

    report = rag_eval_service.run_full_evaluation(
        db,
        hospital_id=1,
        cases=[{
            "id": "x",
            "question": "question",
            "expected_answerable": True,
            "expected_any": ["Expected evidence"],
        }],
        delay_seconds=0,
        provider_retry_wait_seconds=0,
        provider_max_retries=1,
    )

    assert report["completed_cases"] == 0
    assert report["provider_error_cases"] == 1
    assert report["evaluation_complete"] is False


def test_retry_recovers_same_case(monkeypatch):
    db, passage = _fake_db_with_passage()

    monkeypatch.setattr(
        rag_eval_service.rag_embedding_service,
        "embed_query",
        lambda q: [1.0, 0.0],
    )
    monkeypatch.setattr(
        rag_eval_service.rag_service,
        "_embedding_candidates",
        lambda passages, vector: [{
            "id": 1,
            "passage": passage,
            "title": None,
            "content": "Expected evidence.",
            "embedding_score": 0.99,
        }],
    )

    calls = {"n": 0}

    def rerank(question, candidates):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return {
            "answerable": True,
            "results": [
                {"id": 1, "relevance": 0.98, "sufficient": True}
            ],
        }

    monkeypatch.setattr(
        rag_eval_service.rag_service,
        "_llm_rerank_once",
        rerank,
    )
    monkeypatch.setattr(
        rag_eval_service.rag_service,
        "_apply_evidence_gate",
        lambda candidates, rerank, max_results: [{
            **candidates[0],
            "rerank_score": 0.98,
        }],
    )

    report = rag_eval_service.run_full_evaluation(
        db,
        hospital_id=1,
        cases=[{
            "id": "x",
            "question": "question",
            "expected_answerable": True,
            "expected_any": ["Expected evidence"],
        }],
        delay_seconds=0,
        provider_retry_wait_seconds=0,
        provider_max_retries=2,
    )

    assert calls["n"] == 2
    assert report["provider_error_cases"] == 0
    assert report["evaluation_complete"] is True
    assert report["answerability_accuracy_percent"] == 100.0
    assert report["retrieval_hit_at_5_percent"] == 100.0
