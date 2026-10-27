"""Security building blocks. Standard library only (no database, no network)."""
import pytest

from app.core import secret_policy
from app.core.rate_limit import FailureTracker, SlidingWindowLimiter, client_ip
from app.core.redact import redact_secrets


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


# ---------------------------------------------------------------- SECRET_KEY


def test_good_secret_is_kept_as_is():
    key = "k" * 40
    assert secret_policy.resolve_secret_key(key, "production") == key
    assert secret_policy.resolve_secret_key(key, "development") == key


@pytest.mark.parametrize(
    "bad", ["", "   ", "change-this-secret-key-later", "secret", "short-key"]
)
def test_unsafe_secret_in_development_is_replaced_by_random_key(bad):
    first = secret_policy.resolve_secret_key(bad, "development")
    second = secret_policy.resolve_secret_key(bad, "development")

    assert not secret_policy.secret_is_unsafe(first)
    assert len(first) >= secret_policy.MIN_SECRET_LENGTH
    assert first != second  # random every time
    assert first != bad


@pytest.mark.parametrize("bad", ["", "change-this-secret-key-later", "x" * 31])
def test_unsafe_secret_in_production_refuses_to_start(bad):
    with pytest.raises(ValueError):
        secret_policy.resolve_secret_key(bad, "production")


def test_old_shipped_default_is_always_unsafe():
    assert secret_policy.secret_is_unsafe("change-this-secret-key-later")


# --------------------------------------------------------- production policy


def _policy(**overrides):
    values = dict(
        app_env="production",
        otp_required=False,
        otp_delivery_mode="console",
        otp_webhook_url="",
        otp_expose_code_in_dev=False,
        allow_insecure_public_actions=False,
    )
    values.update(overrides)
    return secret_policy.production_problems(**values)


def test_development_has_no_production_problems():
    assert _policy(app_env="development") == []


def test_production_without_otp_or_explicit_opt_out_is_rejected():
    assert any("ALLOW_INSECURE_PUBLIC_ACTIONS" in p for p in _policy())


def test_production_with_explicit_opt_out_is_allowed():
    assert _policy(allow_insecure_public_actions=True) == []


def test_production_otp_with_console_delivery_is_rejected():
    problems = _policy(otp_required=True, otp_delivery_mode="console")
    assert any("never receive" in p for p in problems)


def test_production_otp_with_webhook_is_allowed():
    assert (
        _policy(
            otp_required=True,
            otp_delivery_mode="webhook",
            otp_webhook_url="https://sms.example.org/send",
        )
        == []
    )


def test_production_never_exposes_otp_codes():
    problems = _policy(allow_insecure_public_actions=True, otp_expose_code_in_dev=True)
    assert any("OTP_EXPOSE_CODE_IN_DEV" in p for p in problems)


# ----------------------------------------------------------------- passwords


@pytest.mark.parametrize("weak", ["admin123", "short", "Password1", "", "12345678"])
def test_weak_passwords_are_rejected(weak):
    assert secret_policy.password_problem(weak, "admin@hospital.com")


def test_password_equal_to_email_name_is_rejected():
    assert secret_policy.password_problem("receptionist", "receptionist@hospital.com")


def test_reasonable_password_is_accepted():
    assert secret_policy.password_problem("correct-horse-battery", "a@b.org") == ""


# -------------------------------------------------------------- rate limiter


def test_limiter_blocks_after_limit_and_recovers():
    clock = FakeClock()
    limiter = SlidingWindowLimiter(clock=clock)

    assert [limiter.hit("ip", 3, 60)[0] for _ in range(3)] == [True, True, True]

    allowed, retry_after = limiter.hit("ip", 3, 60)
    assert allowed is False
    assert 1 <= retry_after <= 61

    clock.advance(61)
    assert limiter.hit("ip", 3, 60)[0] is True


def test_limiter_keys_are_independent():
    limiter = SlidingWindowLimiter(clock=FakeClock())
    for _ in range(2):
        limiter.hit("a", 2, 60)

    assert limiter.hit("a", 2, 60)[0] is False
    assert limiter.hit("b", 2, 60)[0] is True


def test_limiter_limit_zero_means_unlimited():
    limiter = SlidingWindowLimiter(clock=FakeClock())
    assert all(limiter.hit("ip", 0, 60)[0] for _ in range(100))


def test_limiter_window_slides_instead_of_resetting_all_at_once():
    clock = FakeClock()
    limiter = SlidingWindowLimiter(clock=clock)

    limiter.hit("ip", 2, 60)      # t=0
    clock.advance(40)
    limiter.hit("ip", 2, 60)      # t=40
    clock.advance(25)             # t=65: first hit expired, second still counts
    assert limiter.hit("ip", 2, 60)[0] is True
    assert limiter.hit("ip", 2, 60)[0] is False


# ------------------------------------------------------------ failure tracker


def test_tracker_locks_after_max_failures_then_expires():
    clock = FakeClock()
    tracker = FailureTracker(clock=clock)

    for _ in range(4):
        assert tracker.register_failure("appt:7", max_failures=5, window_seconds=900, lockout_seconds=900) == 0
    assert tracker.locked_for("appt:7") == 0

    assert tracker.register_failure("appt:7", max_failures=5, window_seconds=900, lockout_seconds=900) == 900
    assert tracker.locked_for("appt:7") > 0

    clock.advance(901)
    assert tracker.locked_for("appt:7") == 0


def test_tracker_success_clears_failures():
    tracker = FailureTracker(clock=FakeClock())
    for _ in range(4):
        tracker.register_failure("k", max_failures=5, window_seconds=900, lockout_seconds=900)

    tracker.register_success("k")

    # Four more failures are again below the limit.
    for _ in range(4):
        assert tracker.register_failure("k", max_failures=5, window_seconds=900, lockout_seconds=900) == 0
    assert tracker.locked_for("k") == 0


def test_tracker_failures_outside_window_do_not_count():
    clock = FakeClock()
    tracker = FailureTracker(clock=clock)

    for _ in range(4):
        tracker.register_failure("k", max_failures=5, window_seconds=60, lockout_seconds=900)
    clock.advance(120)

    assert tracker.register_failure("k", max_failures=5, window_seconds=60, lockout_seconds=900) == 0


def test_tracker_keys_are_independent():
    tracker = FailureTracker(clock=FakeClock())
    for _ in range(5):
        tracker.register_failure("a", max_failures=5, window_seconds=900, lockout_seconds=900)

    assert tracker.locked_for("a") > 0
    assert tracker.locked_for("b") == 0


# ------------------------------------------------------------------ client IP


def test_forwarded_header_ignored_unless_trusted():
    assert client_ip("10.0.0.5", "1.2.3.4", trust_proxy_headers=False) == "10.0.0.5"


def test_forwarded_header_used_when_trusted():
    assert client_ip("10.0.0.5", "1.2.3.4, 10.0.0.1", trust_proxy_headers=True) == "1.2.3.4"


def test_unknown_client_falls_back_safely():
    assert client_ip(None, None, trust_proxy_headers=True) == "unknown"


# ------------------------------------------------------------- log redaction


def test_gemini_key_in_url_is_redacted():
    text = "HTTPSConnectionPool: url: /v1beta/models/x:generateContent?key=AIzaSyA1234567890abcdefghijklmnop"
    cleaned = redact_secrets(text)
    assert "AIza" not in cleaned
    assert "key=<redacted>" in cleaned


def test_bearer_token_is_redacted():
    assert "abcdef123456" not in redact_secrets("Authorization: Bearer abcdef123456789")


def test_configured_literal_secret_is_redacted_in_any_shape():
    secret = "my-very-private-provider-key"
    cleaned = redact_secrets(f"provider said: invalid credential {secret}!", [secret])
    assert secret not in cleaned


def test_header_style_key_is_redacted():
    cleaned = redact_secrets("headers={'x-goog-api-key': 'ZZZZ1234567890'}")
    assert "ZZZZ1234567890" not in cleaned


def test_ordinary_text_is_untouched():
    text = "Gemini HTTP 429: You exceeded your current quota, please check your plan"
    assert redact_secrets(text) == text
    assert redact_secrets(None) == ""
