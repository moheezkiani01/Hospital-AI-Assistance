"""In-memory rate limiting and verification-failure lockout. Standard library only.

Process-local by design (simple, no extra infrastructure). If you run several API
workers/servers, replace the two classes' storage with Redis; the interface stays
the same.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable, Deque, Dict, Optional, Tuple


class SlidingWindowLimiter:
    """Allow at most `limit` hits per `window_seconds` for each key."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._hits: Dict[str, Deque[float]] = {}
        self._last_prune = clock()

    def hit(self, key: str, limit: int, window_seconds: float) -> Tuple[bool, int]:
        """Record a hit. Returns (allowed, retry_after_seconds)."""
        if limit <= 0:
            return True, 0

        now = self._clock()
        with self._lock:
            self._prune(now, window_seconds)
            bucket = self._hits.setdefault(key, deque())
            cutoff = now - window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= limit:
                retry_after = int(bucket[0] + window_seconds - now) + 1
                return False, max(1, retry_after)

            bucket.append(now)
            return True, 0

    def _prune(self, now: float, window_seconds: float) -> None:
        # Cheap periodic cleanup so abandoned keys do not accumulate forever.
        if now - self._last_prune < max(60.0, window_seconds):
            return
        self._last_prune = now
        cutoff = now - window_seconds
        for key in [k for k, v in self._hits.items() if not v or v[-1] <= cutoff]:
            self._hits.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


class FailureTracker:
    """Count failed verifications per key and lock the key out after too many.

    Used for "appointment ID + phone number" checks so an attacker cannot
    enumerate phone numbers against a known appointment ID.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        # key -> (failure_timestamps, locked_until)
        self._failures: Dict[str, Deque[float]] = {}
        self._locked_until: Dict[str, float] = {}

    def locked_for(self, key: str) -> int:
        """Seconds remaining on the lockout for `key` (0 if not locked)."""
        now = self._clock()
        with self._lock:
            until = self._locked_until.get(key)
            if until is None:
                return 0
            if until <= now:
                self._locked_until.pop(key, None)
                self._failures.pop(key, None)
                return 0
            return int(until - now) + 1

    def register_failure(
        self,
        key: str,
        *,
        max_failures: int,
        window_seconds: float,
        lockout_seconds: float,
    ) -> int:
        """Record a failure. Returns lockout seconds if now locked, else 0."""
        if max_failures <= 0:
            return 0

        now = self._clock()
        with self._lock:
            bucket = self._failures.setdefault(key, deque())
            cutoff = now - window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            bucket.append(now)

            if len(bucket) >= max_failures:
                self._locked_until[key] = now + lockout_seconds
                bucket.clear()
                return int(lockout_seconds)
            return 0

    def register_success(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()
            self._locked_until.clear()


def client_ip(
    direct_host: Optional[str],
    forwarded_for: Optional[str],
    *,
    trust_proxy_headers: bool,
) -> str:
    """Best-effort client identifier for rate limiting."""
    if trust_proxy_headers and forwarded_for:
        first = forwarded_for.split(",")[0].strip()
        if first:
            return first
    return direct_host or "unknown"


# Shared instances used by the API layer.
request_limiter = SlidingWindowLimiter()
verification_failures = FailureTracker()
