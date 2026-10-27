"""Deleting a document must also remove what the chatbot learned from it."""
import json

from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.hospital import Hospital
from app.models.rag_passage import RAGPassage
from app.services import (
    document_service,
    llm_service,
    rag_embedding_service,
    rag_index_service,
    rag_service,
)


def _hospital(db_session, name="Lifecycle Hospital"):
    hospital = Hospital(name=name)
    db_session.add(hospital)
    db_session.commit()
    db_session.refresh(hospital)
    return hospital


def _document_with_passage(db_session, hospital, text="Hours are 9 to 9."):
    document = Document(
        hospital_id=hospital.id, uploaded_by_id=None, file_name="faq.txt",
        stored_file_name="faq.txt", file_path="/nonexistent/faq.txt", document_type="txt",
    )
    db_session.add(document)
    db_session.commit()
    db_session.refresh(document)

    db_session.add(
        DocumentChunk(hospital_id=hospital.id, document_id=document.id, chunk_index=0, content=text)
    )
    db_session.add(
        RAGPassage(
            hospital_id=hospital.id, document_id=document.id, passage_index=0,
            content=text, source_hash="s", content_hash="c",
            embedding_model="gemini-embedding-2", embedding_dim=2,
            embedding_json=json.dumps([1.0, 0.0]),
        )
    )
    db_session.commit()
    return document


def test_delete_document_removes_its_passages_and_chunks(db_session):
    hospital = _hospital(db_session)
    document = _document_with_passage(db_session, hospital)

    document_service.delete_document(db_session, document.id)

    assert db_session.query(RAGPassage).count() == 0
    assert db_session.query(DocumentChunk).count() == 0
    assert db_session.query(Document).count() == 0


def test_delete_document_leaves_other_documents_alone(db_session):
    hospital = _hospital(db_session)
    keep = _document_with_passage(db_session, hospital, "Keep me.")
    drop = _document_with_passage(db_session, hospital, "Drop me.")

    document_service.delete_document(db_session, drop.id)

    remaining = db_session.query(RAGPassage).all()
    assert [p.document_id for p in remaining] == [keep.id]


def test_purge_orphan_passages_removes_only_orphans(db_session):
    hospital = _hospital(db_session)
    live = _document_with_passage(db_session, hospital, "Live.")

    db_session.add(
        RAGPassage(
            hospital_id=hospital.id, document_id=9999, passage_index=0,
            content="From a deleted document.", source_hash="s", content_hash="o",
            embedding_model="gemini-embedding-2", embedding_dim=2,
            embedding_json=json.dumps([1.0, 0.0]),
        )
    )
    db_session.commit()

    assert rag_index_service.purge_orphan_passages(db_session, hospital.id) == 1
    assert [p.document_id for p in db_session.query(RAGPassage).all()] == [live.id]


def test_retrieval_never_answers_from_an_orphaned_passage(db_session, monkeypatch):
    hospital = _hospital(db_session)

    # A stale passage whose document no longer exists (the pre-fix state of the DB).
    db_session.add(
        RAGPassage(
            hospital_id=hospital.id, document_id=9999, passage_index=0,
            content="Hospital timing is 9 AM to 9 PM.", source_hash="s", content_hash="o",
            embedding_model="gemini-embedding-2", embedding_dim=2,
            embedding_json=json.dumps([1.0, 0.0]),
        )
    )
    db_session.commit()

    monkeypatch.setattr(rag_index_service, "ensure_hospital_index", lambda *a, **k: {})
    monkeypatch.setattr(rag_embedding_service, "embed_query", lambda q: [1.0, 0.0])
    monkeypatch.setattr(
        llm_service, "call_brain_json",
        lambda prompt: {"answerable": True, "results": [{"id": 1, "relevance": 0.99, "sufficient": True}]},
    )

    evidence = rag_service.retrieve_document_evidence(
        db_session, hospital.id, "what are the hospital timings?", max_results=2
    )

    assert evidence == []
