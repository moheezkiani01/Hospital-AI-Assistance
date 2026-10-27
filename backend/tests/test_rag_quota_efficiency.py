import json
from types import SimpleNamespace

from app.services import rag_eval_service, rag_service


def test_normal_rag_path_uses_one_reranker_call(db_session, monkeypatch):
    hospital_id = 1

    passages = []
    for i in range(1, 7):
        passages.append(SimpleNamespace(
            id=i,
            hospital_id=hospital_id,
            document_id=1,
            passage_index=i-1,
            source_chunk_start_id=i,
            source_chunk_end_id=i,
            semantic_title=f"p{i}",
            content=f"passage {i}",
            embedding_model="gemini-embedding-2",
            embedding_json=json.dumps([1.0, 0.0] if i == 1 else [0.0, 1.0]),
        ))

    class Query:
        def filter(self, *args, **kwargs): return self
        def order_by(self, *args, **kwargs): return self
        def all(self): return passages

    class DB:
        def query(self, *args, **kwargs): return Query()

    monkeypatch.setattr(
        rag_service.rag_index_service,
        "ensure_hospital_index",
        lambda *a, **k: {},
    )
    monkeypatch.setattr(
        rag_service.rag_embedding_service,
        "embed_query",
        lambda q: [1.0, 0.0],
    )
    monkeypatch.setattr(
        rag_service,
        "_document_names",
        lambda *a, **k: {1: "x.pdf"},
    )

    calls = {"count": 0}

    def fake_rerank(question, candidates):
        calls["count"] += 1
        return {
            "answerable": True,
            "results": [
                {"id": 1, "relevance": 0.99, "sufficient": True}
            ],
        }

    monkeypatch.setattr(rag_service, "_llm_rerank_once", fake_rerank)

    result = rag_service.retrieve_document_evidence(
        DB(),
        hospital_id,
        "arbitrary wording",
        log_query=False,
        deep_recall=False,
    )

    assert calls["count"] == 1
    assert result
    assert result[0]["passage_id"] == 1


def test_embedding_evaluation_never_calls_generative_llm(monkeypatch):
    passage = SimpleNamespace(
        id=1,
        hospital_id=1,
        document_id=1,
        passage_index=0,
        semantic_title="result",
        content="The result takes 24 hours.",
        embedding_model="gemini-embedding-2",
        embedding_json=json.dumps([1.0, 0.0]),
    )

    class Query:
        def filter(self, *args, **kwargs): return self
        def order_by(self, *args, **kwargs): return self
        def all(self): return [passage]

    class DB:
        def query(self, *args, **kwargs): return Query()

    monkeypatch.setattr(
        rag_eval_service.rag_embedding_service,
        "embed_query",
        lambda q: [1.0, 0.0],
    )

    report = rag_eval_service.run_embedding_evaluation(
        DB(),
        hospital_id=1,
        cases=[{
            "id": "x",
            "question": "different wording",
            "expected_answerable": True,
            "expected_any": ["24 hours"],
        }],
        top_k=5,
    )

    assert report["retrieval_recall_at_k_percent"] == 100.0


def test_unsupported_full_eval_is_measured_separately(monkeypatch):
    monkeypatch.setattr(
        rag_eval_service.rag_service,
        "retrieve_document_evidence",
        lambda *a, **k: [],
    )

    report = rag_eval_service.run_full_evaluation(
        object(),
        hospital_id=1,
        cases=[{
            "id": "x",
            "question": "unsupported",
            "expected_answerable": False,
            "expected_any": [],
        }],
        delay_seconds=0,
    )

    assert report["answerability_accuracy_percent"] == 100.0
    assert report["unsupported_rejection_percent"] == 100.0
