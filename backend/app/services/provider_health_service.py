from __future__ import annotations

import re
import threading
import time
from typing import Dict, Optional, Tuple

from app.core.config import settings
from app.core.redact import redact_secrets


_lock = threading.RLock()
_state: Dict[str, dict] = {}


def _enabled() -> bool:
    return bool(getattr(settings, "LLM_CIRCUIT_BREAKER_ENABLED", True))


def _now() -> float:
    return time.monotonic()


def _clean_provider(provider: str) -> str:
    return str(provider or "").strip().lower()


def _retry_after_from_text(error_text: str) -> Optional[float]:
    text = str(error_text or "")
    # Providers express Retry-After in several ways. Handle seconds and
    # millisecond text such as "retry in 842.1ms" without over-cooling.
    second_patterns = (
        r"retry(?:\s+in|\s+after)?\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)\s*s(?:ec(?:ond)?s?)?",
        r"retry-after\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)",
    )
    for pattern in second_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            try:
                return max(0.0, float(match.group(1)))
            except Exception:
                pass

    millisecond_match = re.search(
        r"retry(?:\s+in|\s+after)?\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)\s*ms",
        text,
        flags=re.IGNORECASE,
    )
    if millisecond_match:
        try:
            return max(0.0, float(millisecond_match.group(1)) / 1000.0)
        except Exception:
            pass
    return None


def _failure_category(error_text: str, status_code: Optional[int] = None) -> str:
    text = str(error_text or "").lower()

    if status_code == 429 or "http 429" in text or "quota exceeded" in text or "rate limit" in text:
        return "rate_limit"
    if status_code == 402 or "http 402" in text or "insufficient balance" in text or "payment required" in text:
        return "billing"
    if status_code in {401, 403} or "authentication" in text or "invalid api key" in text:
        return "auth"
    if status_code and 500 <= int(status_code) <= 599:
        return "server"
    if re.search(r"\bhttp\s+5\d\d\b", text):
        return "server"
    if any(
        marker in text
        for marker in (
            "nameresolutionerror",
            "failed to resolve",
            "getaddrinfo failed",
            "connectionerror",
            "connection refused",
            "connection reset",
            "connect timeout",
            "read timed out",
            "timed out",
            "max retries exceeded",
        )
    ):
        return "network"
    if status_code in {400, 404, 422} or "model" in text and "not supported" in text:
        return "configuration"
    return "temporary"


def _cooldown_seconds(
    category: str,
    error_text: str,
    retry_after: Optional[float] = None,
) -> int:
    if category == "rate_limit":
        lowered = str(error_text or "").lower()
        if any(marker in lowered for marker in ("perday", "per day", "per_day", "daily")):
            # Daily quota exhaustion is not resolved by a short retry hint.
            return int(getattr(settings, "LLM_COOLDOWN_QUOTA_SECONDS", 900))
        parsed = retry_after if retry_after is not None else _retry_after_from_text(error_text)
        if parsed is not None and parsed > 0:
            return max(5, min(3600, int(parsed) + 2))
        return int(getattr(settings, "LLM_COOLDOWN_RATE_LIMIT_SECONDS", 45))
    if category == "network":
        return int(getattr(settings, "LLM_COOLDOWN_NETWORK_SECONDS", 30))
    if category == "server":
        base = int(getattr(settings, "LLM_COOLDOWN_SERVER_SECONDS", 20))
        parsed = retry_after if retry_after is not None else _retry_after_from_text(error_text)
        # Provider Retry-After is authoritative for overloads. Bound the wait
        # to prevent malformed/malicious headers from disabling a provider all day.
        if parsed is not None and parsed > 0:
            return max(base, min(900, int(parsed) + 2))
        return base
    if category == "billing":
        # A provider with no balance will not recover in a few seconds. Avoid
        # paying the latency cost on every patient turn. Restarting the API
        # process clears this in-memory circuit immediately after balance is added.
        return int(getattr(settings, "LLM_COOLDOWN_BILLING_SECONDS", 1800))
    if category in {"auth", "configuration"}:
        return int(getattr(settings, "LLM_COOLDOWN_AUTH_SECONDS", 300))
    return int(getattr(settings, "LLM_COOLDOWN_DEFAULT_SECONDS", 15))


def should_skip(provider: str) -> Tuple[bool, int, Optional[str]]:
    """Return whether a provider is inside a temporary circuit-breaker cooldown."""
    if not _enabled():
        return False, 0, None

    name = _clean_provider(provider)
    if not name:
        return False, 0, None

    with _lock:
        item = _state.get(name)
        if not item:
            return False, 0, None

        remaining = float(item.get("cooldown_until", 0.0)) - _now()
        if remaining <= 0:
            _state.pop(name, None)
            return False, 0, None

        return True, max(1, int(remaining)), str(item.get("reason") or "temporary provider failure")


def record_success(provider: str) -> None:
    if not _enabled():
        return
    name = _clean_provider(provider)
    if not name:
        return
    with _lock:
        _state.pop(name, None)


def record_failure(
    provider: str,
    error_text: str,
    *,
    status_code: Optional[int] = None,
    retry_after: Optional[float] = None,
) -> dict:
    """Open a short circuit after the provider has already failed/retried.

    This is intentionally in-memory. It protects one API process immediately.
    When the app later runs multiple workers/servers, move this state to Redis.
    """
    if not _enabled():
        return {"provider": _clean_provider(provider), "cooldown_seconds": 0, "category": "disabled"}

    name = _clean_provider(provider)
    if not name:
        return {"provider": name, "cooldown_seconds": 0, "category": "unknown"}

    category = _failure_category(error_text, status_code=status_code)
    seconds = _cooldown_seconds(category, error_text, retry_after=retry_after)
    now = _now()

    with _lock:
        previous = _state.get(name) or {}
        failures = int(previous.get("failures") or 0) + 1
        _state[name] = {
            "provider": name,
            "category": category,
            "reason": redact_secrets(error_text or "provider failure")[:300],
            "failures": failures,
            "opened_at": now,
            "cooldown_until": now + max(1, seconds),
        }

    return {
        "provider": name,
        "category": category,
        "cooldown_seconds": max(1, seconds),
        "failures": failures,
    }


def snapshot() -> dict:
    """Safe diagnostics; no prompts, keys or patient data are stored here."""
    output = {}
    with _lock:
        for name in list(_state.keys()):
            skip, remaining, reason = should_skip(name)
            if not skip:
                continue
            item = _state.get(name) or {}
            output[name] = {
                "status": "cooldown",
                "remaining_seconds": remaining,
                "category": item.get("category"),
                "failures": item.get("failures", 1),
                "reason": reason,
            }
    return output
