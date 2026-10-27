from app.services import llm_service, rag_index_service


def _units():
    return [
        rag_index_service.SourceUnit("A one.", 1),
        rag_index_service.SourceUnit("A two.", 1),
        rag_index_service.SourceUnit("B one.", 1),
        rag_index_service.SourceUnit("B two.", 1),
    ]


def test_compact_llm_boundaries_are_accepted(monkeypatch):
    monkeypatch.setattr(
        llm_service,
        "call_brain_json",
        lambda prompt: {"groups": [[0, 1], [2, 3]]},
    )

    groups, ai_used = rag_index_service._llm_groups(_units())

    assert ai_used is True
    assert groups == [
        {"start": 0, "end": 1, "title": None},
        {"start": 2, "end": 3, "title": None},
    ]


def test_truncated_or_invalid_llm_json_falls_back_safely(monkeypatch):
    monkeypatch.setattr(
        llm_service,
        "call_brain_json",
        lambda prompt: None,
    )

    groups, ai_used = rag_index_service._llm_groups(_units())

    assert ai_used is False
    assert groups
    assert groups[0]["start"] == 0
    assert groups[-1]["end"] == 3


def test_group_validation_requires_complete_ordered_coverage():
    assert rag_index_service._validate_groups([[0, 1], [2, 3]], 4)
    assert rag_index_service._validate_groups([[0, 0], [2, 3]], 4) is None
    assert rag_index_service._validate_groups([[0, 2]], 4) is None
