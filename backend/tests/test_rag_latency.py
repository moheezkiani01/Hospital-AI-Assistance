from app.services import llm_service, rag_service


def _candidate(i, score):
    return {
        "id": i,
        "title": None,
        "content": f"passage {i}",
        "embedding_score": score,
    }


def test_vector_ranked_normal_path_uses_one_llm_call(monkeypatch):
    candidates = [_candidate(i, 1 - i / 100) for i in range(1, 19)]
    calls = {"count": 0}

    def fake_json(prompt):
        calls["count"] += 1
        return {"a": True, "r": [[1, 0.97, 1], [2, 0.82, 1]]}

    monkeypatch.setattr(llm_service, "call_brain_json", fake_json)

    result = rag_service._llm_rerank(
        "patient asks with different wording",
        candidates,
    )

    assert calls["count"] == 1
    assert result["answerable"] is True
    assert result["results"][0]["id"] == 1


def test_compact_rerank_schema_is_parsed():
    result = rag_service._validate_rerank(
        {"a": True, "r": [[7, 0.95, 1], [9, 0.31, 0]]},
        {7, 9},
    )

    assert result["answerable"] is True
    assert result["results"][0] == {
        "id": 7,
        "relevance": 0.95,
        "sufficient": True,
    }


def test_invalid_compact_ids_are_rejected():
    result = rag_service._validate_rerank(
        {"a": True, "r": [[999, 0.99, 1]]},
        {1, 2, 3},
    )

    assert result["results"] == []
