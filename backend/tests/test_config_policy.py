"""Settings refuse unsafe production configuration."""
import pytest
from pydantic import ValidationError

from app.core.config import Settings

GOOD_KEY = "k" * 48


def _settings(**overrides):
    # _env_file=None: ignore any local .env so the test is hermetic.
    return Settings(_env_file=None, **overrides)


def test_development_defaults_boot_with_a_random_key():
    cfg = _settings()
    assert len(cfg.SECRET_KEY) >= 32
    assert cfg.SECRET_KEY != "change-this-secret-key-later"


def test_production_requires_a_real_secret_key():
    with pytest.raises(ValidationError):
        _settings(APP_ENV="production", ALLOW_INSECURE_PUBLIC_ACTIONS=True)


def test_production_requires_otp_or_explicit_opt_out():
    with pytest.raises(ValidationError):
        _settings(APP_ENV="production", SECRET_KEY=GOOD_KEY)


def test_production_with_explicit_opt_out_boots():
    cfg = _settings(APP_ENV="production", SECRET_KEY=GOOD_KEY, ALLOW_INSECURE_PUBLIC_ACTIONS=True)
    assert cfg.SECRET_KEY == GOOD_KEY


def test_cors_origins_are_parsed_from_a_comma_separated_string():
    cfg = _settings(CORS_ORIGINS="https://a.example, https://b.example ,")
    assert cfg.cors_origin_list == ["https://a.example", "https://b.example"]
