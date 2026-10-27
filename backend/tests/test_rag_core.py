import json

from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.hospital import Hospital
from app.models.rag_passage import RAGPassage
from app.services import (
    llm_service,
    rag_embedding_service,
    rag_index_service,
    rag_service,
)


def _seed_document(db_session, text: str):
    hospital = Hospital(name="RAG Core Test Hospital")
    db_session.add(hospital)
    db_session.commit()
    db_session.refresh(hospital)

    document = Document(
        hospital_id=hospital.id,
        uploaded_by_id=None,
        file_name="knowledge.txt",
        stored_file_name="knowledge.txt",
        file_path="/tmp/knowledge.txt",
        document_type="txt",
    )
    db_session.add(document)
    db_session.commit()
    db_session.refresh(document)

    chunk = DocumentChunk(
        hospital_id=hospital.id,
        document_id=document.id,
        chunk_index=0,
        content=text,
    )
    db_session.add(chunk)
    db_session.commit()
    db_session.refresh(chunk)
    return hospital, document, chunk


def test_semantic_chunker_uses_llm_boundaries_but_preserves_source_text(
    db_session, monkeypatch
):
    source = "Alpha fact one.\n\nAlpha fact two.\n\nBeta fact three."
    hospital, document, _ = _seed_document(db_session, source)

    def fake_json(prompt):
        return {
            "groups": [
                {"start": 0, "end": 1, "title": "first concept"},
                {"start": 2, "end": 2, "title": "second concept"},
            ]
        }

    monkeypatch.setattr(llm_service, "call_brain_json", fake_json)
    monkeypatch.setattr(
        rag_embedding_service,
        "embed_documents",
        lambda items: [None for _ in list(items)],
    )

    result = rag_index_service.rebuild_hospital_index(db_session, hospital.id)
    assert result["rebuilt"] == 1

    rows = (
        db_session.query(RAGPassage)
        .filter(RAGPassage.document_id == document.id)
        .order_by(RAGPassage.passage_index.asc())
        .all()
    )
    assert len(rows) == 2
    assert rows[0].content == "Alpha fact one.\nAlpha fact two."
    assert rows[1].content == "Beta fact three."
    assert "first concept" == rows[0].semantic_title


def test_embedding_plus_llm_rerank_selects_evidence_without_keywords(
    db_session, monkeypatch
):
    hospital, document, _ = _seed_document(
        db_session,
        "First source passage.\n\nSecond source passage.",
    )

    # Build two passages directly; retrieval mechanics are being tested here.
    p1 = RAGPassage(
        hospital_id=hospital.id,
        document_id=document.id,
        passage_index=0,
        content="First source passage.",
        source_hash="s",
        content_hash="a",
        embedding_model="gemini-embedding-2",
        embedding_dim=2,
        embedding_json=json.dumps([1.0, 0.0]),
    )
    p2 = RAGPassage(
        hospital_id=hospital.id,
        document_id=document.id,
        passage_index=1,
        content="Second source passage.",
        source_hash="s",
        content_hash="b",
        embedding_model="gemini-embedding-2",
        embedding_dim=2,
        embedding_json=json.dumps([0.0, 1.0]),
    )
    db_session.add_all([p1, p2])
    db_session.commit()
    db_session.refresh(p1)
    db_session.refresh(p2)

    monkeypatch.setattr(
        rag_index_service,
        "ensure_hospital_index",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        rag_embedding_service,
        "embed_query",
        lambda question: [1.0, 0.0],
    )

    def fake_json(prompt):
        return {
            "answerable": True,
            "results": [
                {"id": p1.id, "relevance": 0.97, "sufficient": True},
                {"id": p2.id, "relevance": 0.10, "sufficient": False},
            ],
        }

    monkeypatch.setattr(llm_service, "call_brain_json", fake_json)

    evidence = rag_service.retrieve_document_evidence(
        db_session,
        hospital.id,
        "completely different wording",
        max_results=3,
    )

    assert len(evidence) == 1
    assert evidence[0]["passage_id"] == p1.id
    assert evidence[0]["rerank_score"] == 0.97


def test_strict_evidence_gate_returns_nothing_when_llm_says_not_answerable(
    db_session, monkeypatch
):
    hospital, document, _ = _seed_document(
        db_session,
        "Stored source text.",
    )
    passage = RAGPassage(
        hospital_id=hospital.id,
        document_id=document.id,
        passage_index=0,
        content="Stored source text.",
        source_hash="s",
        content_hash="a",
        embedding_model="gemini-embedding-2",
        embedding_dim=2,
        embedding_json=json.dumps([1.0, 0.0]),
    )
    db_session.add(passage)
    db_session.commit()

    monkeypatch.setattr(
        rag_index_service,
        "ensure_hospital_index",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        rag_embedding_service,
        "embed_query",
        lambda question: [1.0, 0.0],
    )
    monkeypatch.setattr(
        llm_service,
        "call_brain_json",
        lambda prompt: {"answerable": False, "results": []},
    )

    evidence = rag_service.retrieve_document_evidence(
        db_session,
        hospital.id,
        "unsupported question",
        max_results=3,
    )
    assert evidence == []
