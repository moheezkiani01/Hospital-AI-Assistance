from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional


# This layer validates STRUCTURED model output. It does not classify patient
# language and it does not decide hospital facts. The LLM may suggest an action;
# backend services remain the only authority allowed to read/write real data.

ALLOWED_INTENTS = {
    "book_appointment",
    "stop_workflow",
    "doctor_availability",
    "reschedule_appointment",
    "cancel_appointment",
    "appointment_status",
    "correct_patient_info",
    "doctor_information",
    "hospital_information",
    "general_health_info",
    "medical_safety",
    "emergency",
    "human_support",
    "greeting",
    "thanks",
    "general_question",
    "unknown",
}

MUTATION_OR_SENSITIVE_INTENTS = {
    "stop_workflow",
    "book_appointment",
    "reschedule_appointment",
    "cancel_appointment",
    "correct_patient_info",
    "appointment_status",
}

INFORMATIONAL_SIDE_QUESTION_INTENTS = {
    "doctor_information",
    "hospital_information",
    "general_health_info",
    "general_question",
    "greeting",
    "thanks",
}

ALLOWED_WORKFLOW_ACTIONS = {
    "none",
    "continue",
    "show_alternative_dates",
    "show_alternative_doctors",
    "show_alternative_times",
    "select_date",
    "select_doctor",
    "select_time",
    "provide_phone",
    "provide_name",
    "confirm",
    "proceed_cancel",
    "choose_reschedule",
    "cancel_workflow",
    "answer_side_question",
    "unclear",
}

ACTIONS_BY_INTENT = {
    "stop_workflow": {"cancel_workflow", "none"},
    "book_appointment": {"none", "continue", "select_date", "select_doctor", "select_time", "provide_phone", "provide_name", "confirm", "answer_side_question", "unclear"},
    "doctor_availability": {"none", "show_alternative_dates", "show_alternative_doctors", "show_alternative_times", "select_date", "select_doctor", "select_time", "unclear"},
    "reschedule_appointment": {"none", "continue", "choose_reschedule", "show_alternative_dates", "show_alternative_doctors", "show_alternative_times", "select_date", "select_doctor", "select_time", "provide_phone", "confirm", "cancel_workflow", "unclear"},
    "cancel_appointment": {"none", "continue", "proceed_cancel", "choose_reschedule", "provide_phone", "confirm", "unclear"},
    "appointment_status": {"none", "continue", "provide_phone", "unclear"},
    "correct_patient_info": {"none", "continue", "provide_phone", "confirm", "unclear"},
}

CANONICAL_WEEKDAYS = {
    "monday": "Monday",
    "tuesday": "Tuesday",
    "wednesday": "Wednesday",
    "thursday": "Thursday",
    "friday": "Friday",
    "saturday": "Saturday",
    "sunday": "Sunday",
}


def _clean_text(value: Any, max_length: int = 300) -> Optional[str]:
    if value is None:
        return None
    text = str(value).replace("\x00", "").strip()
    if not text:
        return None
    return text[:max_length]


def _positive_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except Exception:
        return None
    return number if number > 0 else None


def _iso_date(value: Any) -> Optional[str]:
    text = _clean_text(value, 32)
    if not text:
        return None
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d").date()
    except Exception:
        return None
    return parsed.isoformat()


def _canonical_time(value: Any) -> Optional[str]:
    text = _clean_text(value, 32)
    if not text:
        return None
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).time().strftime("%H:%M:%S")
        except Exception:
            continue
    return None


def _canonical_weekday(value: Any) -> Optional[str]:
    text = _clean_text(value, 20)
    if not text:
        return None
    return CANONICAL_WEEKDAYS.get(text.lower())


def guard_understanding(data: Optional[dict]) -> Dict[str, Any]:
    """Sanitize one structured LLM decision before backend routing.

    Security goals:
    - reject malformed IDs/dates/times instead of trusting model output;
    - remove fields that are incompatible with the selected intent;
    - never let an LLM assert that a sensitive operation is verified/authorized;
    - prevent side-question flags from hiding a mutation request;
    - cap free-text arguments so prompt/tool output cannot become an unbounded
      payload passed deeper into application code.
    """
    if not isinstance(data, dict):
        return {}

    result = dict(data)

    intent = str(result.get("intent") or "unknown").strip()
    if intent not in ALLOWED_INTENTS:
        intent = "unknown"
    result["intent"] = intent

    action = str(result.get("workflow_action") or "none").strip().lower()
    if action not in ALLOWED_WORKFLOW_ACTIONS:
        action = "unclear"
    allowed_for_intent = ACTIONS_BY_INTENT.get(intent)
    if allowed_for_intent is not None and action not in allowed_for_intent:
        action = "unclear"
    result["workflow_action"] = action

    result["appointment_id"] = _positive_int(result.get("appointment_id"))
    result["doctor_id"] = _positive_int(result.get("doctor_id"))
    result["excluded_doctor_id"] = _positive_int(result.get("excluded_doctor_id"))

    result["appointment_date"] = _iso_date(result.get("appointment_date"))
    result["excluded_date"] = _iso_date(result.get("excluded_date"))
    result["appointment_time"] = _canonical_time(result.get("appointment_time"))
    result["requested_weekday"] = _canonical_weekday(result.get("requested_weekday"))

    for field, max_length in (
        ("doctor_name", 160),
        ("doctor_specialty", 160),
        ("excluded_doctor_name", 160),
        ("patient_name", 200),
        ("patient_phone", 50),
        ("search_text", 240),
        ("correction_field", 50),
        ("old_value", 240),
        ("new_value", 240),
        ("short_reason", 300),
        ("language_style", 30),
        ("availability_scope", 40),
        ("requested_view", 50),
        ("information_target", 50),
        ("requested_field", 50),
    ):
        result[field] = _clean_text(result.get(field), max_length)

    # These flags are hints only. They can never grant authorization.
    for field in (
        "doctor_exclusion",
        "doctor_alternative_request",
        "date_alternative_request",
        "availability_query",
        "date_was_mentioned",
        "time_was_mentioned",
        "is_side_question",
        "resume_active_workflow",
    ):
        result[field] = bool(result.get(field))

    # Date/time mention flags follow sanitized structured values, not arbitrary
    # model claims. requested_weekday counts as a real date selection signal.
    result["date_was_mentioned"] = bool(result.get("appointment_date") or result.get("requested_weekday"))
    result["time_was_mentioned"] = bool(result.get("appointment_time"))

    # Correction fields are meaningful only inside the dedicated correction
    # workflow. Backend still verifies phone/record ownership before any write.
    if intent != "correct_patient_info":
        result["correction_field"] = None
        result["old_value"] = None
        result["new_value"] = None
        result["existing_record_correction"] = False
    else:
        result["existing_record_correction"] = True

    # A mutation/sensitive action cannot masquerade as a harmless side question.
    if intent not in INFORMATIONAL_SIDE_QUESTION_INTENTS:
        result["is_side_question"] = False
        result["resume_active_workflow"] = False

    # The backend owns whether an action needs validation/execution. Never accept
    # this authority flag from the LLM itself.
    result["needs_backend_action"] = intent in MUTATION_OR_SENSITIVE_INTENTS or intent in {
        "doctor_availability",
        "doctor_information",
        "hospital_information",
    }

    return result
