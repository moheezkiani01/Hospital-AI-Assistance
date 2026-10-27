from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError


@dataclass(frozen=True)
class ErrorInfo:
    code: str
    patient_message: str
    retryable: bool = False
    clear_selected_time: bool = False


_ERROR_RULES = (
    (
        ("selected appointment slot is not available", "slot is not available"),
        ErrorInfo(
            "SLOT_TAKEN",
            "The selected appointment time is no longer available. Please choose another available time.",
            retryable=True,
            clear_selected_time=True,
        ),
    ),
    (
        ("you already have an appointment with this doctor on this date",),
        ErrorInfo(
            "DUPLICATE_APPOINTMENT",
            "You already have an active appointment with this doctor on that date. Use the existing appointment or reschedule it instead of creating another one.",
        ),
    ),
    (
        ("appointment not found",),
        ErrorInfo("APPOINTMENT_NOT_FOUND", "I could not find that appointment in this hospital's records."),
    ),
    (
        ("phone number does not match this appointment",),
        ErrorInfo("PHONE_MISMATCH", "The phone number does not match the appointment record."),
    ),
    (
        ("doctor not found or inactive", "selected doctor", "doctor not found"),
        ErrorInfo("DOCTOR_UNAVAILABLE", "The selected doctor is not currently available for this action."),
    ),
    (
        ("no schedule found",),
        ErrorInfo("NO_SCHEDULE", "That doctor does not have an active schedule for the selected day."),
    ),
    (
        ("past date", "cannot book an appointment for a past date"),
        ErrorInfo("PAST_DATE", "Appointments cannot be booked for a past date."),
    ),
    (
        ("past time", "time has already passed"),
        ErrorInfo("PAST_TIME", "That appointment time has already passed. Please choose a future time."),
    ),
    (
        ("hospital not found",),
        ErrorInfo("HOSPITAL_NOT_FOUND", "The hospital record is not available."),
    ),
    (
        ("existing duplicate active appointment slots",),
        ErrorInfo(
            "DATA_CONFLICT",
            "Appointment availability is temporarily inconsistent. Please contact reception or try again after the schedule is corrected.",
        ),
    ),
)


def classify_exception(error: Exception) -> ErrorInfo:
    """Convert internal exceptions into stable, patient-safe categories.

    Raw SQL/provider/internal exception text must never be used as patient-facing
    content. Known business-rule messages become structured codes; unknown errors
    collapse to one generic temporary failure.
    """
    text = str(error or "").strip().lower()

    for markers, info in _ERROR_RULES:
        if any(marker in text for marker in markers):
            return info

    if isinstance(error, IntegrityError):
        return ErrorInfo(
            "DATABASE_CONFLICT",
            "The appointment changed while your request was being processed. Please choose from the latest available slots.",
            retryable=True,
            clear_selected_time=True,
        )

    if isinstance(error, (OperationalError, SQLAlchemyError)):
        return ErrorInfo(
            "DATABASE_TEMPORARY_ERROR",
            "The appointment system is temporarily unavailable. Please try again in a moment.",
            retryable=True,
        )

    return ErrorInfo(
        "TEMPORARY_ERROR",
        "I could not complete that appointment action safely. Please try again in a moment.",
        retryable=True,
    )


def build_llm_directive(info: ErrorInfo, *, verified_context: str = "") -> str:
    """Safe authoritative directive for the patient-facing LLM.

    The error code is for internal consistency. The LLM is explicitly told not to
    expose it or invent a different reason.
    """
    parts = [
        f"INTERNAL_ERROR_CODE: {info.code}",
        f"SAFE_PATIENT_FACT: {info.patient_message}",
        "Explain only the SAFE_PATIENT_FACT naturally in the patient's current language/style.",
        "Do not expose the internal error code, exception details, SQL/database details, provider details, or stack traces.",
        "Do not claim the action succeeded.",
    ]
    if verified_context:
        parts.append("VERIFIED_CURRENT_OPTIONS:")
        parts.append(str(verified_context).strip())
    return "\n".join(parts)
