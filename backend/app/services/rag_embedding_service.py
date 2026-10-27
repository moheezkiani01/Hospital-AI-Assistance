import json
import math
from typing import Iterable, Optional

import requests

from app.core.config import settings


def _normalise_vector(values) -> Optional[list[float]]:
    try:
        vector = [float(v) for v in (values or [])]
    except Exception:
        return None

    if not vector:
        return None

    norm = math.sqrt(sum(v * v for v in vector))
    if norm <= 0:
        return None

    return [v / norm for v in vector]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return -1.0
    return float(sum(x * y for x, y in zip(a, b)))


def vector_to_json(vector: Optional[list[float]]) -> Optional[str]:
    if not vector:
        return None
    return json.dumps(vector, separators=(",", ":"))


def vector_from_json(value: Optional[str]) -> Optional[list[float]]:
    if not value:
        return None
    try:
        return _normalise_vector(json.loads(value))
    except Exception:
        return None


def _prepared_text(text: str, *, purpose: str, title: Optional[str] = None) -> str:
    """
    Gemini Embedding 2 uses semantic task instructions in the input text.

    No language vocabulary or Roman-Urdu phrase dictionary is used. The model
    itself maps multilingual text into the same semantic space.
    """
    clean = str(text or "").strip()
    if purpose == "query":
        return f"task: question answering | query: {clean}"

    safe_title = str(title or "none").strip() or "none"
    return f"title: {safe_title} | text: {clean}"


def _embed_one(text: str, *, purpose: str, title: Optional[str] = None) -> Optional[list[float]]:
    api_key = str(getattr(settings, "GEMINI_API_KEY", "") or "").strip()
    model = str(getattr(settings, "RAG_EMBEDDING_MODEL", "gemini-embedding-2") or "").strip()
    dim = int(getattr(settings, "RAG_EMBEDDING_DIM", 768) or 768)

    if not api_key or not model or not str(text or "").strip():
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent"
    payload = {
        "content": {
            "parts": [
                {
                    "text": _prepared_text(text, purpose=purpose, title=title),
                }
            ]
        },
        "embedContentConfig": {
            "outputDimensionality": dim,
            "autoTruncate": True,
        },
    }

    try:
        response = requests.post(
            url,
            headers={
                "x-goog-api-key": api_key,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=float(getattr(settings, "RAG_EMBEDDING_TIMEOUT_SECONDS", 30) or 30),
        )
        if response.status_code >= 400:
            print(
                f"[RAG] embedding provider unavailable: HTTP {response.status_code} "
                f"({model})"
            )
            return None

        data = response.json()
        embedding = data.get("embedding") or {}
        return _normalise_vector(embedding.get("values"))
    except Exception as exc:
        print(f"[RAG] embedding request failed: {type(exc).__name__}")
        return None


def embed_query(text: str) -> Optional[list[float]]:
    return _embed_one(text, purpose="query")


def embed_document(text: str, title: Optional[str] = None) -> Optional[list[float]]:
    return _embed_one(text, purpose="document", title=title)


def embed_documents(
    items: Iterable[tuple[str, Optional[str]]],
) -> list[Optional[list[float]]]:
    """
    Deliberately keeps a simple reliable interface.

    Passage embeddings are cached in SQLite, so document embedding normally
    happens once per changed document rather than on every patient request.
    """
    return [embed_document(text, title=title) for text, title in items]
