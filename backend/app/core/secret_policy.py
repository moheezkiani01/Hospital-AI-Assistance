"""Startup security policy. Standard library only, so it is trivially testable.

Two jobs:
1. Never run with a guessable JWT signing key.
2. In production, refuse to start in a configuration that leaves patient
   appointments modifiable with just "appointment ID + phone number".
"""
from __future__ import annotations

import logging
import secrets
from typing import List

logger = logging.getLogger("hospital_ai.security")

# Values that must never be used to sign tokens (the old shipped default and
# common placeholders).
KNOWN_UNSAFE_SECRETS = frozenset(
    {
        "",
        "change-this-secret-key-later",
        "changeme",
        "change-me",
        "secret",
        "your-secret-key",
        "replace-me",
    }
)

MIN_SECRET_LENGTH = 32


def is_production(app_env: str) -> bool:
    return str(app_env or "").strip().lower() in {"prod", "production"}


def secret_is_unsafe(value: str) -> bool:
    text = str(value or "").strip()
    return text.lower() in KNOWN_UNSAFE_SECRETS or len(text) < MIN_SECRET_LENGTH


def resolve_secret_key(value: str, app_env: str) -> str:
    """Return a usable signing key or raise in production.

    Development: an unsafe/missing key is replaced by a random per-process key
    (a loud warning is logged; tokens stop working after a restart).
    Production: raise so the process does not start.
    """
    if not secret_is_unsafe(value):
        return str(value).strip()

    if is_production(app_env):
        raise ValueError(
            "SECRET_KEY is missing, too short (<32 chars) or a known placeholder. "
            'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )

    logger.warning(
        "SECRET_KEY is missing/unsafe. Using a random per-process key; admin "
        "logins will be invalidated on every restart. Set SECRET_KEY in .env."
    )
    return secrets.token_urlsafe(48)


def production_problems(
    *,
    app_env: str,
    otp_required: bool,
    otp_delivery_mode: str,
    otp_webhook_url: str,
    otp_expose_code_in_dev: bool,
    allow_insecure_public_actions: bool,
) -> List[str]:
    """List reasons the configuration is unsafe for production (empty = OK)."""
    if not is_production(app_env):
        return []

    problems: List[str] = []

    if otp_expose_code_in_dev:
        problems.append("OTP_EXPOSE_CODE_IN_DEV must be false in production")

    if otp_required:
        mode = str(otp_delivery_mode or "").strip().lower()
        if mode != "webhook" or not str(otp_webhook_url or "").strip():
            problems.append(
                "OTP_REQUIRED_FOR_SENSITIVE_ACTIONS is true but OTP_DELIVERY_MODE "
                "is not 'webhook' with OTP_SMS_WEBHOOK_URL set, so patients would "
                "never receive their code"
            )
    elif not allow_insecure_public_actions:
        problems.append(
            "public cancel/reschedule/status are protected only by appointment ID + "
            "phone number. Enable OTP (OTP_REQUIRED_FOR_SENSITIVE_ACTIONS=true with "
            "webhook delivery) or explicitly accept the risk with "
            "ALLOW_INSECURE_PUBLIC_ACTIONS=true"
        )

    return problems


MIN_PASSWORD_LENGTH = 10

_WEAK_PASSWORDS = frozenset(
    {
        "admin123",
        "admin",
        "password",
        "password1",
        "12345678",
        "123456789",
        "1234567890",
        "qwerty123",
        "letmein123",
    }
)


def password_problem(password: str, email: str = "") -> str:
    """Return a human-readable reason the password is unacceptable, or '' if OK."""
    value = str(password or "")

    if len(value) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."

    if value.strip().lower() in _WEAK_PASSWORDS:
        return "That password is too common. Choose a different one."

    local_part = str(email or "").split("@")[0].strip().lower()
    if local_part and value.strip().lower() == local_part:
        return "Password must not be the same as the email name."

    return ""
