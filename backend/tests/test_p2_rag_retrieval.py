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


def _seed(db_session):
    hospital = Hospital(name="RAG Test Hospital")
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
        content="Source A.\n\nSource B.",
    )
    db_session.add(chunk)
    db_session.commit()
    return hospital, document


def test_rag_returns_llm_verified_semantic_evidence(db_session, monkeypatch):
    hospital, document = _seed(db_session)

    passage = RAGPassage(
        hospital_id=hospital.id,
        document_id=document.id,
        passage_index=0,
        content="Source A.",
        source_hash="s",
        content_hash="a",
        embedding_model="gemini-embedding-2",
        embedding_dim=2,
        embedding_json=json.dumps([1.0, 0.0]),
    )
    db_session.add(passage)
    db_session.commit()
    db_session.refresh(passage)

    monkeypatch.setattr(rag_index_service, "ensure_hospital_index", lambda *a, **k: {})
    monkeypatch.setattr(rag_embedding_service, "embed_query", lambda q: [1.0, 0.0])
    monkeypatch.setattr(
        llm_service,
        "call_brain_json",
        lambda prompt: {
            "answerable": True,
            "results": [
                {"id": passage.id, "relevance": 0.96, "sufficient": True}
            ],
        },
    )

    evidence = rag_service.retrieve_document_evidence(
        db_session, hospital.id, "arbitrary patient wording", max_results=2
    )

    assert len(evidence) == 1
    assert evidence[0]["content"] == "Source A."
    assert evidence[0]["rerank_score"] == 0.96


def test_rag_strictly_rejects_unsupported_answer(db_session, monkeypatch):
    hospital, document = _seed(db_session)

    passage = RAGPassage(
        hospital_id=hospital.id,
        document_id=document.id,
        passage_index=0,
        content="Stored source.",
        source_hash="s",
        content_hash="a",
        embedding_model="gemini-embedding-2",
        embedding_dim=2,
        embedding_json=json.dumps([1.0, 0.0]),
    )
    db_session.add(passage)
    db_session.commit()

    monkeypatch.setattr(rag_index_service, "ensure_hospital_index", lambda *a, **k: {})
    monkeypatch.setattr(rag_embedding_service, "embed_query", lambda q: [1.0, 0.0])
    monkeypatch.setattr(
        llm_service,
        "call_brain_json",
        lambda prompt: {"answerable": False, "results": []},
    )

    assert rag_service.retrieve_document_evidence(
        db_session, hospital.id, "unsupported request", max_results=2
    ) == []


def test_no_language_keyword_dictionary_is_required():
    # Production RAG is model-semantic. This regression test simply verifies
    # the removed legacy vocabulary structures do not return.
    assert not hasattr(rag_service, "STOP_WORDS")
    assert not hasattr(rag_service, "GREETING_WORDS")
    assert not hasattr(rag_service, "THANKS_WORDS")
