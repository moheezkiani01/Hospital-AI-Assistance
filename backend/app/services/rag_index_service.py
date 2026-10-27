import hashlib
import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.rag_passage import RAGPassage
from app.services import llm_service, rag_embedding_service


@dataclass
class SourceUnit:
    content: str
    source_chunk_id: int


def _sha256(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _document_hash(chunks: list[DocumentChunk]) -> str:
    payload = "\n".join(
        f"{chunk.id}:{chunk.chunk_index}:{chunk.content or ''}"
        for chunk in chunks
    )
    return _sha256(payload)


def _split_long_block(text: str, source_chunk_id: int, max_chars: int) -> list[SourceUnit]:
    """
    Structural safety split only.

    This contains no language vocabulary. It uses punctuation/newlines simply
    to prevent a huge paragraph from exceeding the semantic chunking prompt.
    """
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean:
        return []

    if len(clean) <= max_chars:
        return [SourceUnit(clean, source_chunk_id)]

    sentences = re.split(r"(?<=[.!?؟۔])\s+", clean)
    sentences = [s.strip() for s in sentences if s.strip()]
    if len(sentences) <= 1:
        # Last-resort character window; preserves source text and does not infer language.
        return [
            SourceUnit(clean[i:i + max_chars].strip(), source_chunk_id)
            for i in range(0, len(clean), max_chars)
            if clean[i:i + max_chars].strip()
        ]

    units = []
    buffer = []
    size = 0
    for sentence in sentences:
        added = len(sentence) + (1 if buffer else 0)
        if buffer and size + added > max_chars:
            units.append(SourceUnit(" ".join(buffer), source_chunk_id))
            buffer = [sentence]
            size = len(sentence)
        else:
            buffer.append(sentence)
            size += added
    if buffer:
        units.append(SourceUnit(" ".join(buffer), source_chunk_id))
    return units


def _document_units(chunks: list[DocumentChunk]) -> list[SourceUnit]:
    max_unit_chars = int(getattr(settings, "RAG_SOURCE_UNIT_MAX_CHARS", 1100) or 1100)
    output: list[SourceUnit] = []

    for chunk in chunks:
        raw = str(chunk.content or "").strip()
        if not raw:
            continue

        # Blank lines / line breaks are structure, not language-specific keywords.
        blocks = [
            re.sub(r"\s+", " ", part).strip()
            for part in re.split(r"\n\s*\n|\r\n\s*\r\n", raw)
            if str(part or "").strip()
        ]

        if len(blocks) <= 1:
            # Many extractors flatten PDF text into single lines. Preserve line
            # boundaries as possible structural units before the LLM groups them.
            line_blocks = [
                re.sub(r"\s+", " ", part).strip()
                for part in raw.splitlines()
                if str(part or "").strip()
            ]
            if len(line_blocks) > 1:
                blocks = line_blocks

        for block in blocks or [raw]:
            output.extend(_split_long_block(block, chunk.id, max_unit_chars))

    return output


def _fallback_groups(units: list[SourceUnit]) -> list[dict]:
    """
    Provider-independent emergency fallback.

    No phrase/word dictionary is used. It only packs adjacent source units by
    size. The LLM path is preferred and normally decides semantic boundaries.
    """
    target = int(getattr(settings, "RAG_PASSAGE_TARGET_CHARS", 1500) or 1500)
    groups = []
    start = 0
    size = 0

    for index, unit in enumerate(units):
        projected = size + len(unit.content) + (1 if size else 0)
        if index > start and projected > target:
            groups.append({"start": start, "end": index - 1, "title": None})
            start = index
            size = len(unit.content)
        else:
            size = projected

    if units:
        groups.append({"start": start, "end": len(units) - 1, "title": None})
    return groups


def _validate_groups(groups, unit_count: int) -> Optional[list[dict]]:
    """
    Accept compact LLM output such as [[0, 1], [2, 4]].

    Legacy dict output is still accepted so an older provider response does not
    break indexing. Compact ranges dramatically reduce completion-token usage
    and the chance of truncated JSON.
    """
    if not isinstance(groups, list) or unit_count <= 0:
        return None

    cleaned = []
    expected_start = 0

    for item in groups:
        title = None

        if isinstance(item, (list, tuple)):
            if len(item) < 2:
                return None
            raw_start, raw_end = item[0], item[1]
            if len(item) >= 3 and item[2]:
                title = str(item[2]).strip()[:300] or None

        elif isinstance(item, dict):
            raw_start = item.get("start")
            raw_end = item.get("end")
            if item.get("title"):
                title = str(item.get("title")).strip()[:300] or None

        else:
            return None

        try:
            group_start = int(raw_start)
            group_end = int(raw_end)
        except Exception:
            return None

        if (
            group_start != expected_start
            or group_end < group_start
            or group_end >= unit_count
        ):
            return None

        cleaned.append(
            {
                "start": group_start,
                "end": group_end,
                "title": title,
            }
        )
        expected_start = group_end + 1

    if expected_start != unit_count:
        return None

    return cleaned


def _llm_groups(units: list[SourceUnit]) -> tuple[list[dict], bool]:
    """
    Ask the LLM to choose semantic boundaries only.

    The response is intentionally tiny:
        {"groups":[[0,1],[2,4],[5,5]]}

    The model never rewrites source text. This avoids large JSON completions and
    keeps semantic chunking reliable even with providers that have low output
    limits.
    """
    if not units:
        return [], True

    rendered_units = "\n".join(
        f"[{i}] {unit.content}"
        for i, unit in enumerate(units)
    )

    prompt = f"""
You are the semantic chunking engine for a hospital RAG index.

Group the numbered source units into self-contained passages for question answering.

Requirements:
- Decide boundaries by meaning, not by keyword or vocabulary lists.
- Group only adjacent units.
- Cover every unit exactly once and preserve original order.
- Do not skip, duplicate, reorder, rewrite, summarize, translate, or invent text.
- Prefer one coherent topic, procedure, policy, instruction, or fact group per passage.
- Keep enough surrounding context to answer a focused future question.
- Return ONLY compact minified JSON. No explanation and no markdown.

Required format:
{{"groups":[[0,1],[2,4],[5,5]]}}

Each pair is [start_unit_index,end_unit_index].

SOURCE UNITS:
{rendered_units}
""".strip()

    data = llm_service.call_brain_json(prompt)
    groups = (
        _validate_groups((data or {}).get("groups"), len(units))
        if isinstance(data, dict)
        else None
    )

    if groups:
        return groups, True

    # Provider failure or malformed/truncated JSON: preserve indexing by using a
    # structural size-based fallback. This contains no language vocabulary and
    # never changes source facts.
    return _fallback_groups(units), False


def _semantic_groups(units: list[SourceUnit]) -> list[dict]:
    if not units:
        return []

    max_prompt_chars = int(
        getattr(settings, "RAG_CHUNKING_BATCH_CHARS", 4800) or 4800
    )
    max_provider_failures = int(
        getattr(settings, "RAG_CHUNKING_MAX_PROVIDER_FAILURES", 2) or 2
    )

    all_groups = []
    batch_start = 0
    consecutive_provider_failures = 0
    use_llm = True

    while batch_start < len(units):
        batch_end = batch_start
        size = 0

        while batch_end < len(units):
            added = len(units[batch_end].content) + 24
            if batch_end > batch_start and size + added > max_prompt_chars:
                break
            size += added
            batch_end += 1

        batch = units[batch_start:batch_end]

        if use_llm:
            local_groups, ai_used = _llm_groups(batch)
            if ai_used:
                consecutive_provider_failures = 0
            else:
                consecutive_provider_failures += 1
                if consecutive_provider_failures >= max_provider_failures:
                    # Do not hammer providers for every remaining chunk when the
                    # provider chain is already unavailable. Embeddings and later
                    # semantic reranking can still operate on these safe passages.
                    use_llm = False
                    print(
                        "[RAG] semantic chunking providers unavailable; "
                        "using structural fallback for remaining batches."
                    )
        else:
            local_groups = _fallback_groups(batch)

        for group in local_groups:
            all_groups.append(
                {
                    "start": group["start"] + batch_start,
                    "end": group["end"] + batch_start,
                    "title": group.get("title"),
                }
            )

        batch_start = batch_end

    return all_groups


def _passages_from_units(units: list[SourceUnit], groups: list[dict]) -> list[dict]:
    passages = []
    for passage_index, group in enumerate(groups):
        selected = units[group["start"]:group["end"] + 1]
        content = "\n".join(unit.content for unit in selected).strip()
        if not content:
            continue
        passages.append({
            "passage_index": passage_index,
            "title": group.get("title"),
            "content": content,
            "source_chunk_start_id": selected[0].source_chunk_id,
            "source_chunk_end_id": selected[-1].source_chunk_id,
        })
    return passages


def index_document(db: Session, document: Document, *, force: bool = False) -> dict:
    chunks = (
        db.query(DocumentChunk)
        .filter(
            DocumentChunk.hospital_id == document.hospital_id,
            DocumentChunk.document_id == document.id,
        )
        .order_by(DocumentChunk.chunk_index.asc(), DocumentChunk.id.asc())
        .all()
    )

    if not chunks:
        return {"document_id": document.id, "indexed": False, "reason": "no_source_chunks", "passages": 0}

    source_hash = _document_hash(chunks)
    existing = (
        db.query(RAGPassage)
        .filter(
            RAGPassage.hospital_id == document.hospital_id,
            RAGPassage.document_id == document.id,
        )
        .order_by(RAGPassage.passage_index.asc())
        .all()
    )

    if (
        not force
        and existing
        and all(row.source_hash == source_hash for row in existing)
    ):
        # Fill embeddings that were unavailable OR were built with an older
        # embedding model. Embedding spaces from different models must not be
        # compared with each other.
        model = str(getattr(settings, "RAG_EMBEDDING_MODEL", "gemini-embedding-2"))
        missing = [
            row
            for row in existing
            if (not row.embedding_json) or row.embedding_model != model
        ]
        if missing:
            dim = int(getattr(settings, "RAG_EMBEDDING_DIM", 768) or 768)
            vectors = rag_embedding_service.embed_documents(
                (row.content, row.semantic_title or document.file_name)
                for row in missing
            )
            changed = False
            for row, vector in zip(missing, vectors):
                if vector:
                    row.embedding_model = model
                    row.embedding_dim = len(vector) or dim
                    row.embedding_json = rag_embedding_service.vector_to_json(vector)
                    changed = True
            if changed:
                db.commit()

        return {
            "document_id": document.id,
            "indexed": False,
            "reason": "up_to_date",
            "passages": len(existing),
        }

    # Rebuild the derived index atomically at document level.
    if existing:
        for row in existing:
            db.delete(row)
        db.flush()

    units = _document_units(chunks)
    if not units:
        db.commit()
        return {"document_id": document.id, "indexed": False, "reason": "empty_text", "passages": 0}

    groups = _semantic_groups(units)
    passages = _passages_from_units(units, groups)

    model = str(getattr(settings, "RAG_EMBEDDING_MODEL", "gemini-embedding-2"))
    vectors = rag_embedding_service.embed_documents(
        (item["content"], item.get("title") or document.file_name)
        for item in passages
    )

    for item, vector in zip(passages, vectors):
        row = RAGPassage(
            hospital_id=document.hospital_id,
            document_id=document.id,
            passage_index=item["passage_index"],
            source_chunk_start_id=item["source_chunk_start_id"],
            source_chunk_end_id=item["source_chunk_end_id"],
            semantic_title=item.get("title"),
            content=item["content"],
            source_hash=source_hash,
            content_hash=_sha256(item["content"]),
            embedding_model=model if vector else None,
            embedding_dim=len(vector) if vector else None,
            embedding_json=rag_embedding_service.vector_to_json(vector),
        )
        db.add(row)

    db.commit()
    return {
        "document_id": document.id,
        "indexed": True,
        "reason": "rebuilt",
        "passages": len(passages),
        "embedded": sum(1 for vector in vectors if vector),
    }


def purge_orphan_passages(db: Session, hospital_id: Optional[int] = None) -> int:
    """Delete passages whose source document no longer exists.

    Deleting a document used to leave its passages behind, so retrieval could keep
    quoting facts from a document the admin had already removed.
    Returns the number of rows removed.
    """
    query = db.query(RAGPassage).filter(
        ~RAGPassage.document_id.in_(select(Document.id))
    )
    if hospital_id is not None:
        query = query.filter(RAGPassage.hospital_id == hospital_id)

    removed = query.delete(synchronize_session=False)
    db.commit()
    return int(removed or 0)


def ensure_hospital_index(db: Session, hospital_id: int, *, force: bool = False) -> dict:
    try:
        orphans_removed = purge_orphan_passages(db, hospital_id)
    except Exception:
        db.rollback()
        orphans_removed = 0

    documents = (
        db.query(Document)
        .filter(Document.hospital_id == hospital_id)
        .order_by(Document.id.asc())
        .all()
    )

    stats = {
        "hospital_id": hospital_id,
        "documents": len(documents),
        "rebuilt": 0,
        "passages": 0,
        "embedded": 0,
        "orphans_removed": orphans_removed,
    }

    for document in documents:
        result = index_document(db, document, force=force)
        if result.get("indexed"):
            stats["rebuilt"] += 1
        stats["passages"] += int(result.get("passages") or 0)
        stats["embedded"] += int(result.get("embedded") or 0)

    return stats


def rebuild_hospital_index(db: Session, hospital_id: int) -> dict:
    return ensure_hospital_index(db, hospital_id, force=True)



def get_hospital_index_health(db: Session, hospital_id: int) -> dict:
    """
    Report whether each hospital document is indexed with the current source
    content and current embedding model.
    """
    documents = (
        db.query(Document)
        .filter(Document.hospital_id == hospital_id)
        .order_by(Document.id.asc())
        .all()
    )
    current_model = str(
        getattr(settings, "RAG_EMBEDDING_MODEL", "gemini-embedding-2")
    )

    rows = []
    stale_count = 0
    unembedded_count = 0

    for document in documents:
        chunks = (
            db.query(DocumentChunk)
            .filter(
                DocumentChunk.hospital_id == hospital_id,
                DocumentChunk.document_id == document.id,
            )
            .order_by(DocumentChunk.chunk_index.asc(), DocumentChunk.id.asc())
            .all()
        )
        source_hash = _document_hash(chunks) if chunks else None
        passages = (
            db.query(RAGPassage)
            .filter(
                RAGPassage.hospital_id == hospital_id,
                RAGPassage.document_id == document.id,
            )
            .order_by(RAGPassage.passage_index.asc())
            .all()
        )

        stale = bool(
            chunks
            and (
                not passages
                or any(row.source_hash != source_hash for row in passages)
            )
        )
        unembedded = sum(
            1
            for row in passages
            if not row.embedding_json or row.embedding_model != current_model
        )

        stale_count += 1 if stale else 0
        unembedded_count += unembedded

        rows.append({
            "document_id": document.id,
            "file_name": document.file_name,
            "source_chunks": len(chunks),
            "rag_passages": len(passages),
            "stale": stale,
            "unembedded_passages": unembedded,
        })

    return {
        "hospital_id": hospital_id,
        "documents": len(documents),
        "stale_documents": stale_count,
        "unembedded_passages": unembedded_count,
        "healthy": stale_count == 0 and unembedded_count == 0,
        "items": rows,
    }
