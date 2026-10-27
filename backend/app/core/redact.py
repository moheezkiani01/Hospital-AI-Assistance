"""Remove secrets from text before it is logged or stored. Standard library only."""
from __future__ import annotations

import re
from typing import Iterable

_PATTERNS = (
    # ?key=AIza... / &api_key=... / ?token=...
    (re.compile(r"(?i)\b((?:api[_-]?)?key|token|access_token|secret)=([^&\s\"'<>]+)"), r"\1=<redacted>"),
    # Authorization: Bearer xxx / Bearer xxx
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"), "Bearer <redacted>"),
    # x-goog-api-key: xxx  /  "x-goog-api-key": "xxx"
    (re.compile(r"(?i)(x-goog-api-key['\"]?\s*[:=]\s*['\"]?)[^\s'\",}]+"), r"\1<redacted>"),
    # Google API keys and common provider key shapes appearing bare in text.
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}\b"), "<redacted>"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b"), "<redacted>"),
)


def redact_secrets(text: object, extra_secrets: Iterable[str] = ()) -> str:
    """Return `text` with API keys / tokens masked.

    `extra_secrets` are literal values (e.g. the configured provider keys) that
    must never appear, even in shapes the patterns do not know.
    """
    value = "" if text is None else str(text)

    for secret in extra_secrets:
        secret = str(secret or "").strip()
        if len(secret) >= 8:
            value = value.replace(secret, "<redacted>")

    for pattern, replacement in _PATTERNS:
        value = pattern.sub(replacement, value)

    return value
