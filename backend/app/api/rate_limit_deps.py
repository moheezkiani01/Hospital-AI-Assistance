"""FastAPI glue for the in-memory rate limiter (see app/core/rate_limit.py)."""
from fastapi import HTTPException, Request, status

from app.core.config import settings
from app.core.rate_limit import client_ip, request_limiter


def rate_limited(bucket: str, per_minute_setting: str):
    """Return a dependency that allows N requests/minute per client IP.

    `per_minute_setting` is the NAME of an int setting, e.g.
    "RATE_LIMIT_CHAT_PER_MINUTE", so limits stay configurable from .env.
    """

    def dependency(request: Request) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return

        limit = int(getattr(settings, per_minute_setting))
        ip = client_ip(
            request.client.host if request.client else None,
            request.headers.get("x-forwarded-for"),
            trust_proxy_headers=settings.TRUST_PROXY_HEADERS,
        )

        allowed, retry_after = request_limiter.hit(f"{bucket}:{ip}", limit, 60)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please wait a moment and try again.",
                headers={"Retry-After": str(retry_after)},
            )

    return dependency


chat_rate_limit = rate_limited("chat", "RATE_LIMIT_CHAT_PER_MINUTE")
public_rate_limit = rate_limited("public", "RATE_LIMIT_PUBLIC_PER_MINUTE")
login_rate_limit = rate_limited("login", "RATE_LIMIT_LOGIN_PER_MINUTE")
