from app.services import llm_service


class _Response:
    status_code = 200
    headers = {}
    text = ""

    def json(self):
        return {
            "candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [{"text": '{"ok": true}'}]},
            }]
        }


def test_gemini_key_is_sent_in_a_header_not_the_url(monkeypatch):
    seen = {}

    def fake_post(url, json=None, timeout=None, headers=None, **kwargs):
        seen["url"] = url
        seen["headers"] = headers or {}
        return _Response()

    monkeypatch.setattr(llm_service.requests, "post", fake_post)
    monkeypatch.setattr(llm_service, "GEMINI_API_KEY", "test-key-123456789")
    monkeypatch.setattr(llm_service, "GEMINI_MODEL", "test-model")

    llm_service.call_gemini_json("return JSON")

    assert "key=" not in seen["url"]
    assert "test-key-123456789" not in seen["url"]
    assert seen["headers"].get("x-goog-api-key") == "test-key-123456789"
