from app.services import rag_eval_service, rag_monitor_service, rag_service


def test_semantic_rewrite_uses_llm_not_vocabulary(monkeypatch):
    monkeypatch.setattr(
        rag_service.llm_service,
        "call_brain_json",
        lambda prompt: {"q": "formal semantic retrieval query"},
    )

    rewritten = rag_service._semantic_query_rewrite(
        "arbitrary patient wording"
    )

    assert rewritten == "formal semantic retrieval query"
    assert not hasattr(rag_service, "STOP_WORDS")
    assert not hasattr(rag_service, "ROMAN_URDU_WORDS")


def test_safe_preview_masks_contact_identifiers(monkeypatch):
    monkeypatch.setattr(
        rag_monitor_service.settings,
        "RAG_STORE_SANITIZED_QUERY_PREVIEW",
        True,
        raising=False,
    )

    preview = rag_monitor_service._safe_preview(
        "contact me at patient@example.com or 03001234567"
    )

    assert "patient@example.com" not in preview
    assert "03001234567" not in preview
    assert "<email>" in preview
    assert "<number>" in preview


def test_eval_metrics_measure_supported_and_unsupported(monkeypatch):
    def fake_retrieve(db, hospital_id, question, max_results=5, log_query=False):
        if question == "supported":
            return [{"content": "The result takes 24 hours.", "document_name": "x.pdf"}]
        return []

    monkeypatch.setattr(
        rag_eval_service.rag_service,
        "retrieve_document_evidence",
        fake_retrieve,
    )

    report = rag_eval_service.run_evaluation(
        object(),
        hospital_id=1,
        cases=[
            {
                "id": "a",
                "question": "supported",
                "expected_answerable": True,
                "expected_any": ["24 hours"],
            },
            {
                "id": "b",
                "question": "unsupported",
                "expected_answerable": False,
                "expected_any": [],
            },
        ],
    )

    assert report["answerability_accuracy_percent"] == 100.0
    assert report["retrieval_hit_at_5_percent"] == 100.0
    assert report["unsupported_rejection_percent"] == 100.0
