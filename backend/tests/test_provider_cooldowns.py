from app.services import provider_health_service as health


def setup_function(_):
    health._state.clear()


def test_daily_quota_exhaustion_gets_a_long_cooldown():
    info = health.record_failure(
        "gemini",
        "Gemini HTTP 429: You exceeded your current quota. Quota exceeded for metric "
        "generate_content_free_tier_requests, limit: 20 PerDay, model: gemini-2.5-flash",
        status_code=429,
    )
    assert info["category"] == "rate_limit"
    assert info["cooldown_seconds"] >= 600


def test_short_rate_limit_still_uses_the_providers_retry_delay():
    info = health.record_failure(
        "gemini", "Gemini HTTP 429: quota exceeded. Please retry in 12.5s", status_code=429
    )
    assert 10 <= info["cooldown_seconds"] <= 20


def test_insufficient_balance_is_a_long_billing_cooldown():
    info = health.record_failure("deepseek", "DeepSeek tool HTTP 402: Insufficient Balance", status_code=402)
    assert info["category"] == "billing"
    assert info["cooldown_seconds"] >= 1800


def test_error_reason_never_keeps_an_api_key():
    health.record_failure("gemini", "failed at /models/x:generateContent?key=AIzaSyA1234567890abcdefghijklmnop")
    snapshot = health.snapshot()
    assert "AIza" not in snapshot["gemini"]["reason"]
