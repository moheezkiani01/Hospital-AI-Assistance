from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.redact import redact_secrets
from app.db.database import SessionLocal
from app.models.llm_call_log import LLMCallLog


_LLM_CONTEXT: ContextVar[dict] = ContextVar("llm_monitor_context", default={})


@contextmanager
def llm_monitor_context(
    *,
    hospital_id: Optional[int] = None,
    session_id: Optional[str] = None,
    request_id: Optional[str] = None,
):
    token = _LLM_CONTEXT.set(
        {
            "hospital_id": hospital_id,
            "session_id": session_id,
            "request_id": request_id,
        }
    )
    try:
        yield
    finally:
        _LLM_CONTEXT.reset(token)


def get_context() -> dict:
    return dict(_LLM_CONTEXT.get() or {})


def record_llm_call(
    *,
    provider: str,
    model: Optional[str],
    call_type: str,
    success: bool,
    latency_ms: Optional[int] = None,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
    total_tokens: Optional[int] = None,
    token_count_source: Optional[str] = "estimated",
    input_chars: Optional[int] = None,
    output_chars: Optional[int] = None,
    status_code: Optional[int] = None,
    error_message: Optional[str] = None,
    fallback_from: Optional[str] = None,
):
    """
    Best-effort telemetry. Never stores prompts or patient messages, and never
    breaks the patient's request if the monitoring database write fails.
    """
    ctx = get_context()
    db = SessionLocal()
    try:
        db.info["disable_auto_audit"] = True
        row = LLMCallLog(
            hospital_id=ctx.get("hospital_id"),
            session_id=(str(ctx.get("session_id"))[:150] if ctx.get("session_id") else None),
            request_id=(str(ctx.get("request_id"))[:80] if ctx.get("request_id") else None),
            provider=str(provider or "unknown")[:50],
            model=(str(model)[:150] if model else None),
            call_type=str(call_type or "text")[:30],
            success=bool(success),
            fallback_from=(str(fallback_from)[:80] if fallback_from else None),
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            token_count_source=(str(token_count_source)[:30] if token_count_source else None),
            input_chars=input_chars,
            output_chars=output_chars,
            status_code=status_code,
            error_message=(
                redact_secrets(
                    error_message,
                    (settings.GEMINI_API_KEY, settings.DEEPSEEK_API_KEY, settings.HCN_API_KEY),
                )[:2000]
                if error_message
                else None
            ),
        )
        db.add(row)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
    except Exception:
        db.rollback()
    finally:
        db.close()
