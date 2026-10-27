import json
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, time
from typing import Any, Dict, Optional

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session as SASession

from app.models.audit_log import AuditLog


_AUDIT_CONTEXT: ContextVar[dict] = ContextVar(
    "hospital_audit_context",
    default={},
)

_INSTALLED = False


@contextmanager
def audit_context(
    *,
    hospital_id: Optional[int] = None,
    actor_type: str = "system",
    actor_user_id: Optional[int] = None,
    session_id: Optional[str] = None,
    request_id: Optional[str] = None,
):
    token = _AUDIT_CONTEXT.set(
        {
            "hospital_id": hospital_id,
            "actor_type": actor_type or "system",
            "actor_user_id": actor_user_id,
            "session_id": session_id,
            "request_id": request_id,
        }
    )
    try:
        yield
    finally:
        _AUDIT_CONTEXT.reset(token)


def get_audit_context() -> dict:
    return dict(_AUDIT_CONTEXT.get() or {})


def _safe_json_value(value: Any):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    return str(value)


def _masked_value(model_name: str, field: str, value: Any):
    """Avoid putting raw PHI/secrets into audit metadata."""
    if model_name == "Patient" and field in {"name", "email"}:
        return "<redacted>" if value else None
    if model_name == "Patient" and field == "phone":
        digits = "".join(ch for ch in str(value or "") if ch.isdigit())
        return f"***{digits[-4:]}" if digits else None
    if field in {"hashed_password", "password", "api_key", "secret_key"}:
        return "<redacted>"
    return _safe_json_value(value)


# Only business entities worth auditing. Chat logs/LLM logs/OTP logs are not audited
# to prevent noisy recursive logs.
_AUDITED_FIELDS = {
    "Appointment": {
        "hospital_id",
        "doctor_id",
        "patient_id",
        "appointment_date",
        "appointment_time",
        "status",
        "reason",
    },
    "Patient": {"hospital_id", "name", "phone", "email"},
    "Doctor": {"hospital_id", "name", "specialization", "consultation_fee", "is_active"},
    "Schedule": {
        "hospital_id",
        "doctor_id",
        "day_of_week",
        "start_time",
        "end_time",
        "slot_duration_minutes",
        "is_active",
    },
    "HospitalService": {"hospital_id", "name", "is_active"},
    "LabTest": {"hospital_id", "name", "price", "report_time", "sample_type", "is_active"},
    "FAQ": {"hospital_id", "question", "answer", "is_active"},
    "Document": {"hospital_id", "title", "file_name", "is_active"},
}


def _build_change_payload(obj, is_new: bool = False) -> Dict[str, Any]:
    model_name = obj.__class__.__name__
    fields = _AUDITED_FIELDS.get(model_name, set())
    state = inspect(obj)
    changes: Dict[str, Any] = {}

    for field in fields:
        if not hasattr(obj, field):
            continue

        value = getattr(obj, field, None)
        if is_new:
            changes[field] = {"new": _masked_value(model_name, field, value)}
            continue

        try:
            history = state.attrs[field].history
        except Exception:
            continue

        if not history.has_changes():
            continue

        old_value = history.deleted[0] if history.deleted else None
        new_value = history.added[0] if history.added else value
        changes[field] = {
            "old": _masked_value(model_name, field, old_value),
            "new": _masked_value(model_name, field, new_value),
        }

    return changes


def _make_audit_log(obj, action: str, changes: dict) -> AuditLog:
    ctx = get_audit_context()
    hospital_id = ctx.get("hospital_id")
    if hospital_id is None:
        hospital_id = getattr(obj, "hospital_id", None)

    entity_id = getattr(obj, "id", None)

    return AuditLog(
        hospital_id=hospital_id,
        actor_type=str(ctx.get("actor_type") or "system")[:50],
        actor_user_id=ctx.get("actor_user_id"),
        session_id=(str(ctx.get("session_id"))[:150] if ctx.get("session_id") else None),
        request_id=(str(ctx.get("request_id"))[:80] if ctx.get("request_id") else None),
        action=action,
        entity_type=obj.__class__.__name__,
        entity_id=str(entity_id) if entity_id is not None else None,
        outcome="success",
        changed_fields=",".join(sorted(changes.keys())) if changes else None,
        metadata_json=json.dumps({"changes": changes}, ensure_ascii=False, default=str)[:12000],
    )


def install_audit_listeners():
    """Install once. It must never block the main transaction."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    @event.listens_for(SASession, "before_flush")
    def _audit_before_flush(session, flush_context, instances):  # noqa: ARG001
        if session.info.get("disable_auto_audit"):
            return

        pending_logs = []

        for obj in list(session.new):
            if isinstance(obj, AuditLog):
                continue
            model_name = obj.__class__.__name__
            if model_name not in _AUDITED_FIELDS:
                continue
            changes = _build_change_payload(obj, is_new=True)
            pending_logs.append(_make_audit_log(obj, "create", changes))

        for obj in list(session.dirty):
            if isinstance(obj, AuditLog):
                continue
            model_name = obj.__class__.__name__
            if model_name not in _AUDITED_FIELDS:
                continue
            changes = _build_change_payload(obj, is_new=False)
            if changes:
                pending_logs.append(_make_audit_log(obj, "update", changes))

        for obj in list(session.deleted):
            if isinstance(obj, AuditLog):
                continue
            model_name = obj.__class__.__name__
            if model_name not in _AUDITED_FIELDS:
                continue
            changes = _build_change_payload(obj, is_new=False)
            pending_logs.append(_make_audit_log(obj, "delete", changes))

        for log in pending_logs:
            session.add(log)


def log_explicit_event(
    db,
    *,
    action: str,
    entity_type: str,
    entity_id: Optional[Any] = None,
    hospital_id: Optional[int] = None,
    outcome: str = "success",
    metadata: Optional[dict] = None,
):
    """Use for security/auth/read events that are not DB model mutations."""
    ctx = get_audit_context()
    log = AuditLog(
        hospital_id=hospital_id if hospital_id is not None else ctx.get("hospital_id"),
        actor_type=str(ctx.get("actor_type") or "system")[:50],
        actor_user_id=ctx.get("actor_user_id"),
        session_id=(str(ctx.get("session_id"))[:150] if ctx.get("session_id") else None),
        request_id=(str(ctx.get("request_id"))[:80] if ctx.get("request_id") else None),
        action=str(action)[:100],
        entity_type=str(entity_type)[:80],
        entity_id=str(entity_id) if entity_id is not None else None,
        outcome=str(outcome or "success")[:30],
        metadata_json=(json.dumps(metadata or {}, ensure_ascii=False, default=str)[:12000]),
    )
    db.add(log)
    # Do not commit here. Let the caller's transaction own the commit.
    return log
