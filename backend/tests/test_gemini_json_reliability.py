
from app.services import llm_service


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.headers = {}
        self.text = ""

    def json(self):
        return self._payload


def test_gemini_retries_truncated_json(monkeypatch):
    calls = []
    responses = iter([
        FakeResponse({
            "candidates": [{
                "finishReason": "MAX_TOKENS",
                "content": {"parts": [{"text": '{"intent":"hospital_information","confidence":0.9'}]},
            }]
        }),
        FakeResponse({
            "candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [{"text": '{"intent":"hospital_information","confidence":0.9}'}]},
            }]
        }),
    ])

    def fake_post(url, json=None, timeout=None, **kwargs):
        calls.append(json["generationConfig"]["maxOutputTokens"])
        return next(responses)

    monkeypatch.setattr(llm_service.requests, "post", fake_post)
    monkeypatch.setattr(llm_service, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm_service, "GEMINI_MODEL", "test-model")

    raw = llm_service.call_gemini_json("return JSON")
    parsed = llm_service.extract_json_from_text(raw)

    assert parsed == {"intent": "hospital_information", "confidence": 0.9}
    assert calls == [1800, 2600]


def test_valid_json_uses_one_call(monkeypatch):
    calls = []

    def fake_post(url, json=None, timeout=None, **kwargs):
        calls.append(json["generationConfig"]["maxOutputTokens"])
        return FakeResponse({
            "candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [{"text": '{"a":true,"r":[[1,0.97,1]]}'}]},
            }]
        })

    monkeypatch.setattr(llm_service.requests, "post", fake_post)
    monkeypatch.setattr(llm_service, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm_service, "GEMINI_MODEL", "test-model")

    raw = llm_service.call_gemini_json("return JSON")
    assert llm_service.extract_json_from_text(raw)["a"] is True
    assert calls == [1800]
