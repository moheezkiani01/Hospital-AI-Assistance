import json
import re
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.appointment import Appointment
from app.models.appointment_draft import AppointmentDraft
from app.models.chat_log import ChatLog
from app.models.department import Department
from app.models.doctor import Doctor
from app.models.emergency_contact import EmergencyContact
from app.models.hospital import Hospital
from app.models.hospital_service import HospitalService
from app.models.lab_test import LabTest
from app.models.patient import Patient
from app.models.schedule import Schedule
from app.schemas.chat import ChatMessageRequest
from app.schemas.public_booking import PublicBookAppointmentRequest
from app.core.config import settings
from app.core.rate_limit import verification_failures
from app.services import brain_service, conversation_context_service, error_service, faq_service, llm_service, public_booking_service, rag_service, patient_memory_service


# Natural-language intent is handled by the LLM brain.
# Backend code below keeps only deterministic validation/state logic.

DAY_ORDER = {
    "Monday": 1,
    "Tuesday": 2,
    "Wednesday": 3,
    "Thursday": 4,
    "Friday": 5,
    "Saturday": 6,
    "Sunday": 7
}

WEEKDAY_INDEX = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def resolve_next_weekday_date(weekday_name: str, reference_date: Optional[date] = None):
    """Resolve a semantic weekday selection to its next upcoming calendar date.

    A bare weekday is intentionally treated as the NEXT occurrence. If today is
    the same weekday, the result is seven days later. Explicit today/tomorrow or
    exact dates arrive as appointment_date and therefore take precedence.
    """
    clean_name = str(weekday_name or "").strip().lower()
    target = WEEKDAY_INDEX.get(clean_name)
    if target is None:
        return None

    base_date = reference_date or date.today()
    days_ahead = (target - base_date.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return base_date + timedelta(days=days_ahead)


def resolve_semantic_date(ai_understanding: dict, message: str = ""):
    """Prefer an exact LLM date, then a semantic weekday, then safe English fallback."""
    parsed = parse_date_value((ai_understanding or {}).get("appointment_date"))
    if parsed:
        return parsed

    weekday_date = resolve_next_weekday_date((ai_understanding or {}).get("requested_weekday"))
    if weekday_date:
        return weekday_date

    if message:
        return get_weekday_date_from_message(message)
    return None


def normalize_message(message: str) -> str:
    return message.lower().strip()


def normalize_session_id(session_id: Optional[str]) -> str:
    if not session_id:
        return "default"

    clean_session_id = str(session_id).strip()

    if not clean_session_id:
        return "default"

    return clean_session_id[:150]


def normalize_source(source: Optional[str]) -> str:
    if not source:
        return "website"

    clean_source = str(source).lower().strip()

    if clean_source not in ["website", "whatsapp"]:
        return "website"

    return clean_source


# ============================================================
# AI-FIRST UNDERSTANDING LAYER
# ============================================================
# Purpose:
# 1) AI understands messy human language first.
# 2) Backend validates database facts and performs safe actions.
# 3) Patient-language meaning is not implemented as growing keyword dictionaries.

def get_current_appointment_draft_text(db: Session, hospital_id: int, session_id: str):
    draft = get_active_appointment_draft(
        db=db,
        hospital_id=hospital_id,
        session_id=session_id
    )

    if not draft:
        return "No active appointment draft."

    return build_current_draft_text(draft)


def build_recent_appointment_context(db: Session, hospital_id: int, chat_history: str):
    appointment_ids = []

    if chat_history:
        for match in re.findall(r"Appointment ID\s*:?\s*(\d+)", chat_history, flags=re.IGNORECASE):
            try:
                appointment_ids.append(int(match))
            except Exception:
                pass

    if not appointment_ids:
        return "No recent appointment ID found in chat history."

    appointment_id = appointment_ids[-1]

    appointment = (
        db.query(Appointment)
        .filter(
            Appointment.id == appointment_id,
            Appointment.hospital_id == hospital_id
        )
        .first()
    )

    if not appointment:
        return f"Recent appointment ID {appointment_id} was mentioned, but not found in database."

    doctor = get_doctor_by_id(
        db=db,
        hospital_id=hospital_id,
        doctor_id=appointment.doctor_id
    )

    patient = (
        db.query(Patient)
        .filter(
            Patient.id == appointment.patient_id,
            Patient.hospital_id == hospital_id
        )
        .first()
    )

    doctor_name = doctor.name if doctor else "Doctor not found"
    patient_name = patient.name if patient else "Patient not found"
    patient_phone = patient.phone if patient else "Phone not found"

    return (
        f"Recent appointment from chat history:\n"
        f"Appointment ID: {appointment.id}\n"
        f"Patient: {patient_name}\n"
        f"Phone: {patient_phone}\n"
        f"Doctor: {doctor_name}\n"
        f"Date: {appointment.appointment_date}\n"
        f"Time: {appointment.appointment_time}\n"
        f"Status: {appointment.status}"
    )


def get_ai_message_understanding(
    db: Session,
    request_data: ChatMessageRequest,
    hospital: Hospital,
    session_id: str,
    chat_history: str
):
    """
    Build verified context and let the central LLM brain understand the turn.

    Natural-language meaning lives in brain_service. This function only gathers
    authoritative backend context; factual validation still happens in the
    existing booking/reschedule/status/cancel services.
    """
    # Fetch these only if native tool routing is unavailable; the JSON
    # fallback can then consume the verified context without extra AI calls.
    appointment_context = lambda: build_appointment_context(
        db=db, hospital_id=request_data.hospital_id
    )
    hospital_context = lambda: build_hospital_context(
        db=db, hospital_id=request_data.hospital_id, message=request_data.message
    )

    current_draft_text = get_current_appointment_draft_text(
        db=db,
        hospital_id=request_data.hospital_id,
        session_id=session_id
    )

    recent_appointment_context = build_recent_appointment_context(
        db=db,
        hospital_id=request_data.hospital_id,
        chat_history=chat_history
    )

    active_workflow_state = compact_conversation_state(
        get_conversation_state(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
        )
    )

    source = normalize_source(getattr(request_data, "source", "website"))
    whatsapp_number = getattr(request_data, "whatsapp_number", None)

    return brain_service.interpret_turn(
        user_message=request_data.message,
        hospital_name=hospital.name,
        source=source,
        whatsapp_number=whatsapp_number,
        active_workflow=active_workflow_state,
        appointment_draft_text=current_draft_text,
        recent_chat=chat_history,
        recent_appointment_context=recent_appointment_context,
        appointment_context=appointment_context,
        hospital_context=hospital_context,
        conversation_language=patient_memory_service.get_conversation_language(
            db, request_data.hospital_id, session_id
        ),
    )

def ai_understanding_to_appointment_extraction(ai_understanding: dict, user_message: str = ""):
    resolved_date = resolve_semantic_date(ai_understanding, user_message)
    return {
        "doctor_name": ai_understanding.get("doctor_name"),
        "doctor_specialty": ai_understanding.get("doctor_specialty"),
        "doctor_id": ai_understanding.get("doctor_id"),
        "appointment_date": resolved_date.isoformat() if resolved_date else None,
        "requested_weekday": ai_understanding.get("requested_weekday"),
        "appointment_time": ai_understanding.get("appointment_time"),
        "patient_name": ai_understanding.get("patient_name"),
        "patient_phone": ai_understanding.get("patient_phone"),
        "availability_query": bool(ai_understanding.get("availability_query")),
        "date_was_mentioned": bool(
            ai_understanding.get("date_was_mentioned")
            or ai_understanding.get("appointment_date")
            or ai_understanding.get("requested_weekday")
            or resolved_date
        ),
        "time_was_mentioned": bool(ai_understanding.get("time_was_mentioned")),
        "confirmation": False,
        "cancel_draft": False
    }


def get_ai_appointment_id(ai_understanding: dict, message: str, chat_history: str = ""):
    value = ai_understanding.get("appointment_id")

    if value:
        try:
            return int(value)
        except Exception:
            pass

    combined_text = f"{message}\n{chat_history or ''}"
    matches = re.findall(r"Appointment ID\s*:?\s*(\d+)", combined_text, flags=re.IGNORECASE)

    if matches:
        try:
            return int(matches[-1])
        except Exception:
            pass

    # If user just says "ID 10"
    matches = re.findall(r"\bID\s*:?\s*(\d+)\b", combined_text, flags=re.IGNORECASE)

    if matches:
        try:
            return int(matches[-1])
        except Exception:
            pass

    return None


def get_appointment_with_patient(db: Session, hospital_id: int, appointment_id: int):
    appointment = (
        db.query(Appointment)
        .filter(
            Appointment.id == appointment_id,
            Appointment.hospital_id == hospital_id
        )
        .first()
    )

    if not appointment:
        return None, None

    patient = (
        db.query(Patient)
        .filter(
            Patient.id == appointment.patient_id,
            Patient.hospital_id == hospital_id
        )
        .first()
    )

    return appointment, patient


def phone_matches(patient_phone: str, given_phone: str):
    if not patient_phone or not given_phone:
        return False

    def clean_phone(value):
        return re.sub(r"\D", "", str(value))

    patient_clean = clean_phone(patient_phone)
    given_clean = clean_phone(given_phone)

    if not patient_clean or not given_clean:
        return False

    if patient_clean == given_clean:
        return True

    # The same real number can be written 0300..., 92300... or +92300.... Compare
    # the 10-digit national tail, and ONLY when both sides carry at least 10
    # digits. Never accept an arbitrary short suffix: that would let anyone
    # authorize an appointment change by guessing the last few digits.
    if len(patient_clean) >= 10 and len(given_clean) >= 10:
        return patient_clean[-10:] == given_clean[-10:]

    return False


PHONE_VERIFICATION_LOCKED_MESSAGE = (
    "Too many incorrect phone verification attempts for this record. "
    "Please try again later or contact reception."
)


def _verification_lock_key(patient) -> str:
    return f"chat:{getattr(patient, 'hospital_id', '')}:{getattr(patient, 'id', '')}"


def verification_is_locked(patient) -> bool:
    return bool(verification_failures.locked_for(_verification_lock_key(patient)))


def record_verification_result(patient, matched: bool) -> None:
    """Count wrong phone guesses per patient record and lock out repeat offenders."""
    key = _verification_lock_key(patient)

    if matched:
        verification_failures.register_success(key)
        return

    lockout_seconds = int(settings.VERIFY_LOCKOUT_MINUTES) * 60
    verification_failures.register_failure(
        key,
        max_failures=int(settings.VERIFY_MAX_FAILURES),
        window_seconds=lockout_seconds,
        lockout_seconds=lockout_seconds,
    )


def phone_matches_with_lockout(patient, given_phone) -> bool:
    """phone_matches() for user-supplied phones: counts failures and honours lockout."""
    if verification_is_locked(patient):
        return False

    matched = phone_matches(patient.phone, given_phone)
    record_verification_result(patient, matched)
    return matched


def clean_phone_digits(value: str):
    if not value:
        return None

    digits = re.sub(r"\D", "", str(value))

    if not digits:
        return None

    return digits


def normalize_booking_phone(value: str):
    """
    Backend validation for patient phone values coming from either the LLM or
    deterministic extraction.

    This is intentionally country-agnostic: it validates only a reasonable
    digit length and does not use language/phrase dictionaries.
    """
    digits = clean_phone_digits(value)
    if not digits:
        return None

    if 7 <= len(digits) <= 15:
        return digits

    return None


def get_state_payload(state: Optional[dict]):
    if not state:
        return {}

    raw_payload = state.get("payload_json") or "{}"

    try:
        payload = json.loads(raw_payload)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass

    return {}


def state_has_verified_phone(state: Optional[dict]):
    if not state:
        return False

    payload = get_state_payload(state)

    return bool(payload.get("phone_verified")) and bool(state.get("patient_phone"))


def extract_phone_from_current_message(message: str):
    """
    Extract phone only from the user's current message.

    This is source-aware verification support, not intent guessing.
    It avoids using appointment IDs, doctor IDs, times, or database values as phone numbers.
    """
    if not message:
        return None

    text_value = str(message)
    lower_text = text_value.lower()

    # Remove structured IDs before numeric extraction.
    lower_text = re.sub(r"\b(?:appointment\s*)?id\s*[:#-]?\s*\d+\b", " ", lower_text)
    lower_text = re.sub(r"\bdoctor\s*id\s*[:#-]?\s*\d+\b", " ", lower_text)
    lower_text = re.sub(r"\bdr\s*id\s*[:#-]?\s*\d+\b", " ", lower_text)

    # Remove explicit time formats before phone extraction.
    lower_text = re.sub(r"\b\d{1,2}\s*[\.:]\s*\d{1,2}\b", " ", lower_text)
    lower_text = re.sub(r"\b\d{1,2}\s*(am|pm|a\.m\.?|p\.m\.?|baje|bjy|bjay|o\s*clock|oclock)\b", " ", lower_text)

    candidates = re.findall(r"(?<!\d)(?:\+?\d[\d\s\-()]{3,}\d)(?!\d)", lower_text)

    for candidate in candidates:
        digits = normalize_booking_phone(candidate)
        if digits:
            return digits

    return None


def verify_patient_phone_for_action(
    source: str,
    whatsapp_number: Optional[str],
    patient: Patient,
    message: str,
    state: Optional[dict]
):
    """
    Professional source-aware verification.

    WhatsApp: the sender number is the verified identity source.
    Website/link: the user must provide a matching phone number in this workflow.
    Database phone is never used by itself to authorize a change.
    """
    source = normalize_source(source)

    if source == "whatsapp" and whatsapp_number:
        clean_whatsapp_number = clean_phone_digits(whatsapp_number)

        if clean_whatsapp_number and phone_matches(patient.phone, clean_whatsapp_number):
            return True, clean_whatsapp_number, None

        return False, clean_whatsapp_number, "WhatsApp number appointment record se match nahi ho raha. Reception se contact karein."

    if verification_is_locked(patient):
        return False, None, PHONE_VERIFICATION_LOCKED_MESSAGE

    current_message_phone = extract_phone_from_current_message(message)

    if current_message_phone:
        matched = phone_matches(patient.phone, current_message_phone)
        record_verification_result(patient, matched)

        if matched:
            return True, current_message_phone, None

        return False, current_message_phone, "Phone number appointment record se match nahi ho raha. Correct phone number bhej dein."

    if state_has_verified_phone(state):
        state_phone = state.get("patient_phone")

        if state_phone and phone_matches(patient.phone, state_phone):
            return True, state_phone, None

    return False, None, "Appointment change secure rakhne ke liye appointment wala phone number verify karna zaroori hai. Please wahi phone number bhej dein."



def extract_phone_candidates_from_current_message(message: str):
    """Return phone-like values typed in the current user message only."""
    if not message:
        return []

    text_value = str(message).lower()

    # Remove IDs and times so they cannot be mistaken for phone numbers.
    text_value = re.sub(r"\b(?:appointment\s*)?id\s*[:#-]?\s*\d+\b", " ", text_value)
    text_value = re.sub(r"\bdoctor\s*id\s*[:#-]?\s*\d+\b", " ", text_value)
    text_value = re.sub(r"\bdr\s*id\s*[:#-]?\s*\d+\b", " ", text_value)
    text_value = re.sub(r"\b\d{1,2}\s*[\.:]\s*\d{1,2}\b", " ", text_value)
    text_value = re.sub(
        r"\b\d{1,2}\s*(am|pm|a\.m\.?|p\.m\.?|baje|bjy|bjay|o\s*clock|oclock)\b",
        " ",
        text_value,
    )

    raw_candidates = re.findall(r"(?<!\d)(?:\+?\d[\d\s\-()]{3,}\d)(?!\d)", text_value)
    candidates = []

    for raw_candidate in raw_candidates:
        digits = clean_phone_digits(raw_candidate)
        if digits and 5 <= len(digits) <= 15 and digits not in candidates:
            candidates.append(digits)

    return candidates


def verify_patient_phone_for_correction(
    source: str,
    whatsapp_number: Optional[str],
    patient: Patient,
    message: str,
    state: Optional[dict],
):
    """
    Verify ownership before a patient record correction.

    Unlike the generic verifier, this checks every phone in the current message.
    This matters for phone changes where a patient may type both the old and new
    number in the same message, in either order.
    """
    source = normalize_source(source)

    if source == "whatsapp" and whatsapp_number:
        clean_whatsapp_number = clean_phone_digits(whatsapp_number)
        if clean_whatsapp_number and phone_matches(patient.phone, clean_whatsapp_number):
            return True, clean_whatsapp_number, None

        return False, clean_whatsapp_number, (
            "WhatsApp number appointment record se match nahi ho raha. Reception se contact karein."
        )

    if verification_is_locked(patient):
        return False, None, PHONE_VERIFICATION_LOCKED_MESSAGE

    current_message_phones = extract_phone_candidates_from_current_message(message)

    for candidate in current_message_phones:
        if phone_matches(patient.phone, candidate):
            record_verification_result(patient, True)
            return True, candidate, None

    if state_has_verified_phone(state):
        state_phone = state.get("patient_phone")
        if state_phone and phone_matches(patient.phone, state_phone):
            return True, state_phone, None

    if current_message_phones:
        # One failure per message, even when the message contains several numbers.
        record_verification_result(patient, False)
        return False, None, (
            "Phone number appointment record se match nahi ho raha. "
            "Correction ke liye appointment wala existing phone number bhej dein."
        )

    return False, None, (
        "Patient information secure rakhne ke liye appointment wala existing phone number "
        "verify karna zaroori hai. Please wahi phone number bhej dein."
    )


def normalize_correction_field(value):
    if not value:
        return None

    clean_value = str(value).strip().lower()

    if clean_value in ["patient_name", "name", "full_name"]:
        return "patient_name"

    if clean_value in ["patient_phone", "phone", "phone_number", "mobile", "mobile_number"]:
        return "patient_phone"

    return None


def normalize_text_for_value_check(value: str):
    value = str(value or "").strip().lower()
    value = re.sub(r"[^\w\s.'-]", " ", value, flags=re.UNICODE)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def correction_value_is_present_in_message(value: str, message: str):
    """Do not trust an AI-extracted name unless the user actually typed it now."""
    clean_value = normalize_text_for_value_check(value)
    clean_message = normalize_text_for_value_check(message)

    if not clean_value or not clean_message:
        return False

    return clean_value in clean_message


def validate_correction_value(correction_field: str, value: str):
    value = str(value or "").strip()

    if correction_field == "patient_phone":
        digits = clean_phone_digits(value)
        if not digits or not 7 <= len(digits) <= 15:
            return False, None, "New phone number valid format me bhej dein."
        return True, digits, None

    if correction_field == "patient_name":
        if not 2 <= len(value) <= 80:
            return False, None, "New patient name clear aur valid bhej dein."

        allowed_chars = set(" -.'")
        if not any(char.isalpha() for char in value):
            return False, None, "New patient name clear aur valid bhej dein."

        if any(not (char.isalpha() or char in allowed_chars) for char in value):
            return False, None, "Patient name me sirf letters, spaces, hyphen ya apostrophe use karein."

        clean_name = re.sub(r"\s+", " ", value).strip()
        return True, clean_name, None

    return False, None, "Sirf patient name ya phone number correct kiya ja sakta hai."


def get_proposed_correction_value(
    correction_field: str,
    ai_understanding: dict,
    message: str,
    patient: Patient,
    pending_value: Optional[str] = None,
):
    """
    Determine the proposed new value without allowing the LLM to invent data.

    Phone: must be a phone number actually present in the current message, and
    it must be different from the currently stored phone.

    Name: an AI-extracted value is accepted only when that exact value is also
    present in the current user message.
    """
    if pending_value:
        return str(pending_value).strip()

    if correction_field == "patient_phone":
        current_phones = extract_phone_candidates_from_current_message(message)
        for candidate in reversed(current_phones):
            if not phone_matches(patient.phone, candidate):
                return candidate
        return None

    if correction_field == "patient_name":
        candidates = [
            ai_understanding.get("new_value"),
            ai_understanding.get("patient_name"),
        ]

        for candidate in candidates:
            if not candidate:
                continue

            candidate = str(candidate).strip()
            if correction_value_is_present_in_message(candidate, message):
                return candidate

    return None


def find_unique_active_appointment_by_phone(db: Session, hospital_id: int, patient_phone: str):
    patient = find_patient_by_phone(
        db=db,
        hospital_id=hospital_id,
        patient_phone=patient_phone
    )

    if not patient:
        return None, []

    appointments = (
        db.query(Appointment)
        .filter(
            Appointment.hospital_id == hospital_id,
            Appointment.patient_id == patient.id,
            Appointment.status.in_(["booked", "confirmed"])
        )
        .order_by(Appointment.appointment_date.asc(), Appointment.appointment_time.asc())
        .all()
    )

    if len(appointments) == 1:
        return appointments[0], appointments

    return None, appointments


def build_active_appointment_list(db: Session, hospital_id: int, appointments: list):
    lines = []

    for appointment in appointments:
        doctor = get_doctor_by_id(
            db=db,
            hospital_id=hospital_id,
            doctor_id=appointment.doctor_id
        )

        doctor_name = doctor.name if doctor else "Doctor"

        lines.append(
            f"Appointment ID {appointment.id}: {doctor_name}, "
            f"{format_date_for_patient(appointment.appointment_date)}, "
            f"{format_time_for_patient(appointment.appointment_time)}, "
            f"status {appointment.status}"
        )

    return "\n".join(lines)



# ============================================================
# BACKEND CORE STATE MACHINE
# ============================================================
# The AI only understands the message. Backend state decides what action is in progress.


def ensure_conversation_states_table(db: Session):
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS conversation_states (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hospital_id INTEGER NOT NULL,
                session_id VARCHAR(150) NOT NULL,
                mode VARCHAR(50),
                step VARCHAR(100),
                appointment_id INTEGER,
                patient_phone VARCHAR(50),
                doctor_id INTEGER,
                appointment_date VARCHAR(20),
                appointment_time VARCHAR(20),
                patient_name VARCHAR(200),
                payload_json TEXT,
                created_at DATETIME,
                updated_at DATETIME,
                UNIQUE(hospital_id, session_id)
            )
            """
        )
    )
    db.commit()


def get_conversation_state(db: Session, hospital_id: int, session_id: str):
    ensure_conversation_states_table(db)

    result = db.execute(
        text(
            """
            SELECT * FROM conversation_states
            WHERE hospital_id = :hospital_id AND session_id = :session_id
            LIMIT 1
            """
        ),
        {
            "hospital_id": hospital_id,
            "session_id": session_id,
        }
    )

    row = result.mappings().first()

    if not row:
        return None

    return dict(row)


def compact_conversation_state(state: Optional[dict]):
    """Return only workflow fields the LLM needs for the next turn.

    Database ids/timestamps and large payloads are intentionally omitted. The
    backend keeps the full row; this compact view is only prompt context.
    """
    if not state:
        return None

    compact = {}
    for key in (
        "mode",
        "step",
        "appointment_id",
        "patient_phone",
        "doctor_id",
        "appointment_date",
        "appointment_time",
        "patient_name",
    ):
        value = state.get(key)
        if value not in (None, ""):
            compact[key] = value

    payload = get_state_payload(state)
    if payload:
        safe_payload = {}
        # Keep only workflow-control facts. Large slot arrays/context are supplied
        # by the authoritative handler when needed, not repeated every turn.
        for key in (
            "phone_verified",
            "retention_offer_made",
            "came_from_cancel_retention",
            "came_from_cancel_flow",
            "date_options_shown",
            "selected_doctor_id",
            "selected_date",
            "selected_time",
        ):
            value = payload.get(key)
            if value not in (None, "", [], {}):
                safe_payload[key] = value
        if safe_payload:
            compact["workflow_flags"] = safe_payload

    return compact or None


def save_conversation_state(
    db: Session,
    hospital_id: int,
    session_id: str,
    mode: str,
    step: str = "collecting",
    appointment_id: Optional[int] = None,
    patient_phone: Optional[str] = None,
    doctor_id: Optional[int] = None,
    appointment_date: Optional[date] = None,
    appointment_time=None,
    patient_name: Optional[str] = None,
    payload: Optional[dict] = None
):
    ensure_conversation_states_table(db)

    appointment_date_text = None
    if appointment_date:
        appointment_date_text = str(appointment_date)

    appointment_time_text = None
    if appointment_time:
        appointment_time_text = time_to_slot_string(appointment_time)

    payload_json = json.dumps(payload or {}, default=str)

    existing = get_conversation_state(
        db=db,
        hospital_id=hospital_id,
        session_id=session_id
    )

    now_text = datetime.utcnow().isoformat(sep=" ")

    if existing:
        db.execute(
            text(
                """
                UPDATE conversation_states
                SET mode = :mode,
                    step = :step,
                    appointment_id = :appointment_id,
                    patient_phone = :patient_phone,
                    doctor_id = :doctor_id,
                    appointment_date = :appointment_date,
                    appointment_time = :appointment_time,
                    patient_name = :patient_name,
                    payload_json = :payload_json,
                    updated_at = :updated_at
                WHERE hospital_id = :hospital_id AND session_id = :session_id
                """
            ),
            {
                "mode": mode,
                "step": step,
                "appointment_id": appointment_id,
                "patient_phone": patient_phone,
                "doctor_id": doctor_id,
                "appointment_date": appointment_date_text,
                "appointment_time": appointment_time_text,
                "patient_name": patient_name,
                "payload_json": payload_json,
                "updated_at": now_text,
                "hospital_id": hospital_id,
                "session_id": session_id,
            }
        )
    else:
        db.execute(
            text(
                """
                INSERT INTO conversation_states (
                    hospital_id, session_id, mode, step, appointment_id, patient_phone,
                    doctor_id, appointment_date, appointment_time, patient_name,
                    payload_json, created_at, updated_at
                ) VALUES (
                    :hospital_id, :session_id, :mode, :step, :appointment_id, :patient_phone,
                    :doctor_id, :appointment_date, :appointment_time, :patient_name,
                    :payload_json, :created_at, :updated_at
                )
                """
            ),
            {
                "hospital_id": hospital_id,
                "session_id": session_id,
                "mode": mode,
                "step": step,
                "appointment_id": appointment_id,
                "patient_phone": patient_phone,
                "doctor_id": doctor_id,
                "appointment_date": appointment_date_text,
                "appointment_time": appointment_time_text,
                "patient_name": patient_name,
                "payload_json": payload_json,
                "created_at": now_text,
                "updated_at": now_text,
            }
        )

    db.commit()

    return get_conversation_state(
        db=db,
        hospital_id=hospital_id,
        session_id=session_id
    )


def clear_conversation_state(db: Session, hospital_id: int, session_id: str):
    ensure_conversation_states_table(db)

    db.execute(
        text(
            """
            DELETE FROM conversation_states
            WHERE hospital_id = :hospital_id AND session_id = :session_id
            """
        ),
        {
            "hospital_id": hospital_id,
            "session_id": session_id,
        }
    )
    db.commit()


def parse_state_date(value):
    if not value:
        return None
    return parse_date_value(value)


def parse_state_time(value):
    if not value:
        return None
    return parse_time_value(value)


def is_waiting_for_time_state(state: Optional[dict]) -> bool:
    """
    A time-only follow-up is accepted only when backend is already waiting for a time.
    This avoids treating IDs, phone numbers, doctor IDs, or record numbers as appointment time.
    """
    if not state:
        return False

    step = str(state.get("step") or "").lower().strip()
    mode = str(state.get("mode") or "").lower().strip()

    return mode in ["booking", "reschedule"] and "time" in step


def message_has_time_signal(message: str) -> bool:
    """
    Generic time signal detection.
    It does not depend on one exact sentence. It only checks whether the user wrote a number
    in a time form: 8:30, 8.30, 8pm, 8 am, or common time-unit markers.
    """
    if not message:
        return False

    text_value = str(message).lower().strip()

    if re.search(r"\b\d{1,2}\s*[\.:]\s*\d{1,2}\b", text_value):
        return True

    if re.search(r"\b\d{1,2}\s*(am|pm|a\.m\.?|p\.m\.?)\b", text_value):
        return True

    if re.search(r"\b\d{1,2}\s*(baje|bjy|bjay|o\s*clock|oclock)\b", text_value):
        return True

    return False


def looks_like_short_time_selection(message: str) -> bool:
    """
    Allows short follow-ups such as 8, 830, 8 wali, or 8 pe only after backend is waiting for time.
    Long messages are not treated as time-only selections.
    """
    if not message:
        return False

    text_value = str(message).lower().strip()

    # If the message contains an explicit time format, it is time-like.
    if message_has_time_signal(text_value):
        return True

    numbers = re.findall(r"\b\d+\b", text_value)

    if len(numbers) != 1:
        return False

    number = numbers[0]

    # Phone/reference numbers should not be treated as time.
    if len(number) > 4:
        return False

    # Short free-text follow-up only. This prevents messages like
    # "id 11 doctor ali slots" from becoming 11:00 AM.
    if len(text_value) > 30:
        return False

    return True


def extract_numeric_time_from_message(message: str, allow_short_number: bool = False):
    """
    Generic numeric time parser.

    Safe rule:
    - Always accept real time formats: 8:30, 8.30, 20:30, 8pm, 8 baje.
    - Accept compact/short numbers like 830 or 8 only when backend is already waiting for time.
    - Never convert random IDs or phone numbers into time.
    """
    if not message:
        return None

    text_value = str(message).lower().strip()

    # Ignore long numeric values such as phone numbers/reference numbers.
    text_without_long_numbers = re.sub(r"\b\d{5,}\b", " ", text_value)

    # 8.30 / 8:30 / 20:30
    match = re.search(r"\b(\d{1,2})\s*[\.:]\s*(\d{1,2})\b", text_without_long_numbers)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}:00"

    # 8 pm / 8 am / 8 baje / 8 bjy
    match = re.search(
        r"\b(\d{1,2})\s*(am|pm|a\.m\.?|p\.m\.?|baje|bjy|bjay|o\s*clock|oclock)\b",
        text_without_long_numbers
    )
    if match:
        hour = int(match.group(1))
        marker = match.group(2)

        if not 0 <= hour <= 23:
            return None

        if marker.startswith("p") and 1 <= hour <= 11:
            hour += 12
        elif marker.startswith("a") and hour == 12:
            hour = 0

        return f"{hour:02d}:00:00"

    if not allow_short_number:
        return None

    if not looks_like_short_time_selection(text_without_long_numbers):
        return None

    # 830 / 2030, accepted only during a time-selection step.
    match = re.search(r"\b(\d{3,4})\b", text_without_long_numbers)
    if match:
        value = match.group(1)
        if len(value) == 3:
            hour = int(value[0])
            minute = int(value[1:])
        else:
            hour = int(value[:2])
            minute = int(value[2:])
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}:00"

    # Single number, accepted only during a time-selection step.
    match = re.search(r"\b(\d{1,2})\b", text_without_long_numbers)
    if match:
        hour = int(match.group(1))
        if 0 <= hour <= 23:
            return f"{hour:02d}:00:00"

    return None


def should_accept_ai_time_from_message(message: str, state: Optional[dict]) -> bool:
    """
    AI may sometimes mistake an ID/reference number as time.
    Backend accepts AI time only when the user's text actually looks time-related,
    or when the current backend step is waiting for a time selection.
    """
    return message_has_time_signal(message) or is_waiting_for_time_state(state)


def choose_slot_from_available_times(raw_time, available_slots: list):
    """
    Chooses the real database slot from an ambiguous user time.
    If user says 8:30 and only 20:30 exists, backend selects 20:30.
    """
    if not raw_time:
        return None

    parsed_time = parse_time_value(raw_time)
    if not parsed_time:
        return None

    direct_slot = parsed_time.strftime("%H:%M:%S")
    if direct_slot in available_slots:
        return direct_slot

    hour = parsed_time.hour
    minute = parsed_time.minute

    if 1 <= hour <= 11:
        pm_slot = f"{hour + 12:02d}:{minute:02d}:00"
        if pm_slot in available_slots:
            return pm_slot

    if 13 <= hour <= 23:
        am_slot = f"{hour - 12:02d}:{minute:02d}:00"
        if am_slot in available_slots:
            return am_slot

    return direct_slot


def merge_reschedule_understanding_with_state(
    db: Session,
    hospital_id: int,
    session_id: str,
    message: str,
    ai_understanding: dict,
    state: Optional[dict]
):
    appointment_id = get_ai_appointment_id(
        ai_understanding=ai_understanding,
        message=message,
        chat_history=""
    )

    if not appointment_id and state:
        appointment_id = state.get("appointment_id")

    patient_phone = ai_understanding.get("patient_phone")
    if not patient_phone and state:
        patient_phone = state.get("patient_phone")

    patient_name = ai_understanding.get("patient_name")
    if not patient_name and state:
        patient_name = state.get("patient_name")

    doctor_id = ai_understanding.get("doctor_id")
    if (not doctor_id) and (ai_understanding.get("doctor_name") or ai_understanding.get("doctor_specialty")):
        matched_doctor, possible_matches = match_doctor(
            db=db,
            hospital_id=hospital_id,
            doctor_id=ai_understanding.get("doctor_id"),
            doctor_name=ai_understanding.get("doctor_name"),
            doctor_specialty=ai_understanding.get("doctor_specialty")
        )
        if matched_doctor:
            doctor_id = matched_doctor.id

    if not doctor_id and state:
        doctor_id = state.get("doctor_id")

    appointment_date = resolve_semantic_date(ai_understanding, message)
    if not appointment_date and state:
        appointment_date = parse_state_date(state.get("appointment_date"))

    allow_short_number_time = is_waiting_for_time_state(state)

    numeric_time = extract_numeric_time_from_message(
        message=message,
        allow_short_number=allow_short_number_time
    )

    appointment_time = None

    if numeric_time:
        appointment_time = parse_time_value(numeric_time)
    elif ai_understanding.get("appointment_time") and should_accept_ai_time_from_message(message, state):
        appointment_time = parse_time_value(ai_understanding.get("appointment_time"))

    if not appointment_time and state:
        appointment_time = parse_state_time(state.get("appointment_time"))

    return {
        "appointment_id": appointment_id,
        "patient_phone": patient_phone,
        "patient_name": patient_name,
        "doctor_id": int(doctor_id) if doctor_id else None,
        "appointment_date": appointment_date,
        "appointment_time": appointment_time,
        "raw_time": numeric_time or (ai_understanding.get("appointment_time") if should_accept_ai_time_from_message(message, state) else None),
    }


def build_missing_reschedule_reply(missing_items: list, details: dict):
    saved_lines = []

    if details.get("appointment_id"):
        saved_lines.append(f"Appointment ID: {details.get('appointment_id')}")
    if details.get("patient_phone"):
        saved_lines.append(f"Phone: {details.get('patient_phone')}")
    if details.get("doctor_id"):
        saved_lines.append(f"Doctor ID: {details.get('doctor_id')}")
    if details.get("appointment_date"):
        saved_lines.append(f"New Date: {format_date_for_patient(details.get('appointment_date'))}")
    if details.get("appointment_time"):
        saved_lines.append(f"New Time: {format_time_for_patient(details.get('appointment_time'))}")

    line_1 = "Appointment change ke liye " + ", ".join(missing_items) + " bhej dein."

    if saved_lines:
        return "Saved details:\n" + "\n".join(saved_lines) + "\n" + line_1

    return line_1



def build_reschedule_date_options(
    db: Session,
    hospital_id: int,
    appointment_id: int,
    start_after_date: Optional[date] = None,
    excluded_date: Optional[date] = None,
    max_dates: int = 3,
    days_ahead: int = 21
):
    """
    Shows the next available dates for rescheduling across all doctors.
    This is schedule-driven and does not depend on one fixed user sentence.
    """
    if start_after_date:
        start_date = start_after_date + timedelta(days=1)
    else:
        start_date = date.today()

    if start_date < date.today():
        start_date = date.today()

    lines = [
        f"Appointment ID {appointment_id} ke liye next available date options:"
    ]

    found_dates = 0

    for day_offset in range(0, days_ahead + 1):
        target_date = start_date + timedelta(days=day_offset)

        if excluded_date and target_date == excluded_date:
            continue

        slots_context, found_any_slot, _ = build_slots_for_all_doctors_for_reschedule(
            db=db,
            hospital_id=hospital_id,
            appointment_date=target_date
        )

        if not found_any_slot:
            continue

        found_dates += 1
        lines.append("")
        lines.append(slots_context)

        if found_dates >= max_dates:
            break

    if found_dates == 0:
        lines.append("Next available dates me free slots nahi mile.")

    lines.append("")
    lines.append("In dates me se date/time choose kar dein. Agar in ke ilawa koi aur date chahiye to woh date bhej dein.")

    return "\n".join(lines), found_dates > 0


def build_contextual_action_reply(user_message: str, base_instruction: str, reply_type: str, chat_history: str = ""):
    # Patient-facing wording is generated once, centrally, in build_chat_response.
    # Keeping this function as a backend directive avoids double LLM calls.
    return str(base_instruction or "").strip()

def handle_ai_reschedule_state_flow(
    db: Session,
    request_data: ChatMessageRequest,
    hospital: Hospital,
    session_id: str,
    chat_history: str,
    ai_understanding: dict,
    current_state: Optional[dict] = None
):
    """
    Professional backend-controlled reschedule state machine.

    Design:
    - State never blocks useful commands.
    - If user asks for options while rescheduling, backend shows real slots.
    - Phone verification is required before changing DB, not before showing slots.
    - Missing date can safely fall back to the current appointment date when an
      appointment is already identified and the user is changing only time.
    - AI is used only for extraction; final action replies are backend facts.
    """
    source = normalize_source(getattr(request_data, "source", "website"))
    whatsapp_number = getattr(request_data, "whatsapp_number", None)

    details = merge_reschedule_understanding_with_state(
        db=db,
        hospital_id=request_data.hospital_id,
        session_id=session_id,
        message=request_data.message,
        ai_understanding=ai_understanding,
        state=current_state
    )

    if source == "whatsapp" and whatsapp_number:
        details["patient_phone"] = str(whatsapp_number).strip()

    appointment = None
    patient = None

    # 1) Find the appointment by ID when available.
    if details.get("appointment_id"):
        appointment, patient = get_appointment_with_patient(
            db=db,
            hospital_id=request_data.hospital_id,
            appointment_id=int(details.get("appointment_id"))
        )

        if not appointment or not patient:
            save_conversation_state(
                db=db,
                hospital_id=request_data.hospital_id,
                session_id=session_id,
                mode="reschedule",
                step="waiting_for_valid_appointment_id",
                appointment_id=details.get("appointment_id"),
                patient_phone=details.get("patient_phone"),
                doctor_id=details.get("doctor_id"),
                appointment_date=details.get("appointment_date"),
                appointment_time=details.get("appointment_time"),
                patient_name=details.get("patient_name"),
            )
            return build_chat_response(
                db=db,
                hospital_id=request_data.hospital_id,
                session_id=session_id,
                message=request_data.message,
                answer="Appointment ID nahi mila. Correct Appointment ID bhej dein.",
                intent="reschedule_appointment_not_found",
                sources=[]
            )

    # 2) If ID is missing but phone is present, try to find one active appointment.
    elif details.get("patient_phone"):
        appointment, appointments = find_unique_active_appointment_by_phone(
            db=db,
            hospital_id=request_data.hospital_id,
            patient_phone=details.get("patient_phone")
        )

        if appointment:
            details["appointment_id"] = appointment.id
            patient = (
                db.query(Patient)
                .filter(Patient.id == appointment.patient_id)
                .first()
            )
        elif len(appointments) > 1:
            appointment_list = build_active_appointment_list(db, request_data.hospital_id, appointments)
            save_conversation_state(
                db=db,
                hospital_id=request_data.hospital_id,
                session_id=session_id,
                mode="reschedule",
                step="waiting_for_appointment_id",
                patient_phone=details.get("patient_phone"),
                doctor_id=details.get("doctor_id"),
                appointment_date=details.get("appointment_date"),
                appointment_time=details.get("appointment_time"),
                patient_name=details.get("patient_name"),
            )
            return build_chat_response(
                db=db,
                hospital_id=request_data.hospital_id,
                session_id=session_id,
                message=request_data.message,
                answer=(
                    "Is phone number par multiple active appointments hain:\n"
                    + appointment_list
                    + "\nJis appointment ko change karna hai us ka Appointment ID bhej dein."
                ),
                intent="reschedule_multiple_need_id",
                sources=[]
            )

    # 3) Appointment is still not identified.
    # At the start of reschedule, collect appointment details first.
    # Website phone verification is required later, before the final database update.
    if not appointment:
        save_conversation_state(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            mode="reschedule",
            step="waiting_for_appointment_id",
            appointment_id=details.get("appointment_id"),
            patient_phone=details.get("patient_phone"),
            doctor_id=details.get("doctor_id"),
            appointment_date=details.get("appointment_date"),
            appointment_time=details.get("appointment_time"),
            patient_name=details.get("patient_name"),
        )

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer="Appointment change ke liye Appointment ID bhej dein. New date, time, ya doctor change karna ho to woh details bhi bhej sakte hain.",
            intent="reschedule_need_appointment_id",
            sources=[]
        )

    # 4) Protect inactive or already-passed appointments.
    reschedule_block_reason = get_appointment_action_block_reason(appointment, "reschedule")
    if reschedule_block_reason:
        clear_conversation_state(db, request_data.hospital_id, session_id)
        answer = make_ai_reply(
            user_message=request_data.message,
            base_instruction=(
                f"Do not reschedule this appointment. Verified backend reason: {reschedule_block_reason} "
                "Explain this briefly in the patient's current language/style. Do not ask for more details and do not claim any change was made."
            ),
            reply_type="reschedule_not_allowed",
            chat_history=chat_history,
        )
        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=answer,
            intent="reschedule_not_allowed",
            sources=[]
        )

    state_step = str((current_state or {}).get("step") or "").lower().strip()
    workflow_action = str(ai_understanding.get("workflow_action") or "none").strip().lower()

    # A patient may abandon the reschedule conversation without cancelling the
    # appointment itself.  The LLM identifies that conversational action; the
    # backend only clears temporary workflow state.
    if workflow_action == "cancel_workflow":
        clear_conversation_state(db, request_data.hospital_id, session_id)
        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer="Theek hai, reschedule process stop kar diya hai. Existing appointment me koi change nahi ki gayi.",
            intent="reschedule_workflow_cancelled",
            sources=[]
        )

    user_supplied_new_date = bool(
        parse_date_value(ai_understanding.get("appointment_date"))
        or ai_understanding.get("requested_weekday")
        or get_weekday_date_from_message(request_data.message)
    )

    # The LLM decides conversational meaning, not availability. If the patient
    # asks for a different date, use the date currently selected/shown in backend
    # state as the date to move away from, then query real future schedules.
    if ai_understanding.get("date_alternative_request") or workflow_action == "show_alternative_dates":
        rejected_date = (
            parse_date_value(ai_understanding.get("excluded_date"))
            or parse_state_date((current_state or {}).get("appointment_date"))
            or parse_date_value(ai_understanding.get("appointment_date"))
            or appointment.appointment_date
        )

        options_text, found_options = build_reschedule_date_options(
            db=db,
            hospital_id=request_data.hospital_id,
            appointment_id=appointment.id,
            start_after_date=rejected_date,
            excluded_date=rejected_date,
            max_dates=3,
            days_ahead=21
        )

        save_conversation_state(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            mode="reschedule",
            step="waiting_for_new_date",
            appointment_id=appointment.id,
            patient_phone=details.get("patient_phone"),
            doctor_id=details.get("doctor_id") or appointment.doctor_id,
            appointment_date=None,
            appointment_time=None,
            patient_name=details.get("patient_name"),
            payload={"date_options_shown": True, "phone_verified": False},
        )

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=options_text,
            intent="reschedule_date_options",
            sources=[]
        )

    if state_step == "waiting_for_new_date" and not user_supplied_new_date:
        options_text, found_options = build_reschedule_date_options(
            db=db,
            hospital_id=request_data.hospital_id,
            appointment_id=appointment.id,
            start_after_date=appointment.appointment_date,
            excluded_date=appointment.appointment_date,
            max_dates=3,
            days_ahead=21
        )

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=options_text,
            intent="reschedule_need_new_date",
            sources=[]
        )

    # 5) Fill safe defaults from the actual appointment.
    # If user is changing only time or asking remaining slots, use the appointment's current date.
    if not details.get("doctor_id"):
        details["doctor_id"] = appointment.doctor_id

    if not details.get("appointment_date"):
        details["appointment_date"] = appointment.appointment_date

    doctor = get_doctor_by_id(
        db=db,
        hospital_id=request_data.hospital_id,
        doctor_id=details.get("doctor_id") or appointment.doctor_id
    )

    if not doctor:
        save_conversation_state(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            mode="reschedule",
            step="waiting_for_doctor",
            appointment_id=details.get("appointment_id"),
            patient_phone=details.get("patient_phone"),
            appointment_date=details.get("appointment_date"),
            appointment_time=details.get("appointment_time"),
            patient_name=details.get("patient_name"),
        )
        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer="Doctor clear nahi hua. Correct doctor name ya Doctor ID bhej dein.",
            intent="reschedule_need_doctor",
            sources=[]
        )

    if details.get("appointment_date") < date.today():
        save_conversation_state(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            mode="reschedule",
            step="waiting_for_future_date",
            appointment_id=details.get("appointment_id"),
            patient_phone=details.get("patient_phone"),
            doctor_id=doctor.id,
            appointment_time=details.get("appointment_time"),
            patient_name=details.get("patient_name"),
        )
        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer="Past date par appointment change nahi ho sakti. Future date bhej dein.",
            intent="reschedule_past_date",
            sources=[]
        )

    selected_doctor_context, available_slots = build_slots_for_selected_doctor(
        db=db,
        hospital_id=request_data.hospital_id,
        doctor=doctor,
        appointment_date=details.get("appointment_date")
    )

    # When the patient asks conversationally for other times, do not keep an
    # earlier selected time from workflow state. Show real slots for the current
    # selected date and let them choose again.
    if workflow_action in {"show_alternative_times", "show_alternative_doctors"}:
        details["appointment_time"] = None
        details["raw_time"] = None

    selected_slot = choose_slot_from_available_times(
        raw_time=details.get("raw_time") or details.get("appointment_time"),
        available_slots=available_slots
    )

    if selected_slot:
        details["appointment_time"] = parse_time_value(selected_slot)

    # 6) If no new time is selected yet, show real reschedule options for the date.
    # For reschedule, patients often need to compare doctors before choosing.
    if not details.get("appointment_time"):
        excluded_doctor_id = get_ai_excluded_doctor_id(
            db=db,
            hospital_id=request_data.hospital_id,
            ai_understanding=ai_understanding
        )

        if not excluded_doctor_id and (
            ai_understanding.get("doctor_alternative_request")
            or workflow_action == "show_alternative_doctors"
        ):
            excluded_doctor_id = details.get("doctor_id") or appointment.doctor_id

        all_doctor_context, found_any_doctor_slot, available_by_doctor = build_slots_for_all_doctors_for_reschedule(
            db=db,
            hospital_id=request_data.hospital_id,
            appointment_date=details.get("appointment_date"),
            excluded_doctor_id=excluded_doctor_id
        )

        save_conversation_state(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            mode="reschedule",
            step="waiting_for_new_time",
            appointment_id=details.get("appointment_id"),
            patient_phone=details.get("patient_phone"),
            doctor_id=doctor.id,
            appointment_date=details.get("appointment_date"),
            patient_name=details.get("patient_name"),
            payload={
                "available_slots": available_slots,
                "available_by_doctor": available_by_doctor,
                "phone_verified": False
            },
        )

        phone_note = "Phone number final confirmation se pehle verify karna hoga." if source != "whatsapp" and not details.get("patient_phone") else ""

        if not found_any_doctor_slot:
            no_slots_answer = (
                f"Appointment ID {appointment.id} ke liye {format_date_for_patient(details.get('appointment_date'))} par koi doctor slot available nahi hai.\n"
                + build_no_all_doctor_slots_reply(
                    db=db,
                    hospital_id=request_data.hospital_id,
                    appointment_date=details.get("appointment_date")
                )
                + (f"\n{phone_note}" if phone_note else "")
            )

            save_conversation_state(
                db=db,
                hospital_id=request_data.hospital_id,
                session_id=session_id,
                mode="reschedule",
                step="waiting_for_new_date",
                appointment_id=details.get("appointment_id"),
                patient_phone=details.get("patient_phone"),
                doctor_id=doctor.id,
                appointment_date=None,
                appointment_time=None,
                patient_name=details.get("patient_name"),
                payload={"phone_verified": False},
            )

            return build_chat_response(
                db=db,
                hospital_id=request_data.hospital_id,
                session_id=session_id,
                message=request_data.message,
                answer=no_slots_answer,
                intent="reschedule_no_slots_show_next_dates",
                sources=[]
            )

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=(
                f"Appointment ID {appointment.id} ke liye {format_date_for_patient(details.get('appointment_date'))} ke available options:\n"
                f"{all_doctor_context}\n"
                "New time choose kar dein. Doctor change karna ho to Doctor ID/name ke sath time bhej dein."
                + (f"\n{phone_note}" if phone_note else "")
            ),
            intent="reschedule_show_all_doctor_slots_waiting_for_time",
            sources=[]
        )

    # 7) Verify identity before changing DB.
    # WhatsApp uses the sender number. Website/link must provide a matching phone number in this workflow.
    phone_verified, verified_phone, phone_error = verify_patient_phone_for_action(
        source=source,
        whatsapp_number=whatsapp_number,
        patient=patient,
        message=request_data.message,
        state=current_state
    )

    if not phone_verified:
        save_conversation_state(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            mode="reschedule",
            step="waiting_for_phone",
            appointment_id=details.get("appointment_id"),
            patient_phone=None,
            doctor_id=doctor.id,
            appointment_date=details.get("appointment_date"),
            appointment_time=details.get("appointment_time"),
            patient_name=details.get("patient_name"),
            payload={
                "available_slots": available_slots,
                "phone_verified": False
            },
        )

        verification_message = phone_error or "Appointment change secure rakhne ke liye appointment wala phone number verify karna zaroori hai. Phone number match hone ke baad hi appointment update hogi."

        answer = build_contextual_action_reply(
            user_message=request_data.message,
            base_instruction=verification_message,
            reply_type="reschedule_phone_verification_required",
            chat_history=chat_history
        )

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=answer,
            intent="reschedule_need_phone_before_update",
            sources=[]
        )

    details["patient_phone"] = verified_phone

    save_conversation_state(
        db=db,
        hospital_id=request_data.hospital_id,
        session_id=session_id,
        mode="reschedule",
        step="phone_verified",
        appointment_id=details.get("appointment_id"),
        patient_phone=verified_phone,
        doctor_id=doctor.id,
        appointment_date=details.get("appointment_date"),
        appointment_time=details.get("appointment_time"),
        patient_name=details.get("patient_name"),
        payload={
            "available_slots": available_slots,
            "phone_verified": True
        },
    )

    selected_time_string = time_to_slot_string(details.get("appointment_time"))

    if selected_time_string not in available_slots:
        save_conversation_state(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            mode="reschedule",
            step="waiting_for_new_time",
            appointment_id=details.get("appointment_id"),
            patient_phone=details.get("patient_phone"),
            doctor_id=doctor.id,
            appointment_date=details.get("appointment_date"),
            patient_name=details.get("patient_name"),
            payload={"available_slots": available_slots, "phone_verified": phone_verified},
        )

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=(
                f"{format_time_for_patient(details.get('appointment_time'))} available nahi hai.\n"
                f"{selected_doctor_context}\n"
                "In available slots me se new time choose kar dein."
            ),
            intent="reschedule_slot_not_available",
            sources=[]
        )

    if appointment.doctor_id == doctor.id and appointment.appointment_date == details.get("appointment_date") and appointment.appointment_time == details.get("appointment_time"):
        save_conversation_state(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            mode="reschedule",
            step="waiting_for_new_time",
            appointment_id=details.get("appointment_id"),
            patient_phone=details.get("patient_phone"),
            doctor_id=doctor.id,
            appointment_date=details.get("appointment_date"),
            patient_name=details.get("patient_name"),
            payload={"available_slots": available_slots, "phone_verified": phone_verified},
        )
        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=(
                "Ye appointment already isi date aur time par hai.\n"
                f"Current time: {format_time_for_patient(appointment.appointment_time)}\n"
                f"Available slots:\n{selected_doctor_context}\n"
                "Change karne ke liye koi different time choose kar dein."
            ),
            intent="reschedule_same_slot_choose_other",
            sources=[]
        )

    # Share the same patient/doctor/day rule with public bookings. A different
    # free time is not sufficient when the patient already has another active
    # appointment with this doctor on the requested day.
    other_same_day = public_booking_service.find_active_patient_doctor_day_appointment(
        db=db,
        hospital_id=request_data.hospital_id,
        patient_id=appointment.patient_id,
        doctor_id=doctor.id,
        appointment_date=details.get("appointment_date"),
        exclude_appointment_id=appointment.id,
    )
    if other_same_day:
        save_conversation_state(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            mode="reschedule",
            step="waiting_for_new_date",
            appointment_id=appointment.id,
            patient_phone=verified_phone,
            doctor_id=doctor.id,
            appointment_date=None,
            appointment_time=None,
            patient_name=details.get("patient_name"),
            payload={"phone_verified": True},
        )
        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=(
                "The patient already has another active appointment with the "
                "selected doctor on this date. No appointment was changed. "
                "Explain this verified conflict naturally and ask for a different "
                "date or doctor. Do not request previously verified details again."
            ),
            intent="reschedule_duplicate_same_day",
            sources=[],
        )

    old_doctor = get_doctor_by_id(db, request_data.hospital_id, appointment.doctor_id)
    old_date = appointment.appointment_date
    old_time = appointment.appointment_time

    # Database-level guard closes the race between the availability read above
    # and this commit. It protects rescheduling as well as new bookings.
    public_booking_service.ensure_active_slot_unique_index(db)

    appointment.doctor_id = doctor.id
    appointment.appointment_date = details.get("appointment_date")
    appointment.appointment_time = details.get("appointment_time")

    if details.get("patient_name"):
        patient.name = str(details.get("patient_name")).strip()

    try:
        db.commit()
        db.refresh(appointment)
    except IntegrityError as error:
        db.rollback()
        try:
            db.refresh(appointment)
            db.refresh(patient)
        except Exception:
            pass

        latest_context, latest_slots = build_slots_for_selected_doctor(
            db=db,
            hospital_id=request_data.hospital_id,
            doctor=doctor,
            appointment_date=details.get("appointment_date")
        )
        save_conversation_state(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            mode="reschedule",
            step="waiting_for_new_time",
            appointment_id=details.get("appointment_id"),
            patient_phone=details.get("patient_phone"),
            doctor_id=doctor.id,
            appointment_date=details.get("appointment_date"),
            patient_name=details.get("patient_name"),
            payload={"available_slots": latest_slots, "phone_verified": True},
        )
        info = error_service.classify_exception(error)
        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=error_service.build_llm_directive(info, verified_context=latest_context),
            intent="reschedule_slot_not_available",
            sources=[],
            safe_fallback_answer=info.patient_message + ("\n" + latest_context if latest_context else ""),
        )

    clear_conversation_state(db, request_data.hospital_id, session_id)

    # The transaction has already committed. Keep a validated receipt ready in
    # case the final LLM request fails or invents a different appointment ID.
    verified_receipt = (
            "Appointment successfully change ho gayi hai.\n"
            f"Appointment ID: {appointment.id}\n"
            f"Patient: {patient.name}\n"
            f"Phone: {patient.phone}\n"
            f"Old Doctor: {old_doctor.name if old_doctor else ''}\n"
            f"Old Date: {format_date_for_patient(old_date)}\n"
            f"Old Time: {format_time_for_patient(old_time)}\n"
            f"New Doctor: {doctor.name}\n"
            f"New Date: {format_date_for_patient(appointment.appointment_date)}\n"
            f"New Time: {format_time_for_patient(appointment.appointment_time)}\n"
            "Appointment ID save kar lein."
    )

    return build_chat_response(
        db=db,
        hospital_id=request_data.hospital_id,
        session_id=session_id,
        message=request_data.message,
        answer=verified_receipt,
        intent="reschedule_completed",
        sources=[],
        safe_fallback_answer=verified_receipt,
    )

def handle_ai_reschedule_flow(
    db: Session,
    request_data: ChatMessageRequest,
    hospital: Hospital,
    session_id: str,
    chat_history: str,
    ai_understanding: dict
):
    current_state = get_conversation_state(
        db=db,
        hospital_id=request_data.hospital_id,
        session_id=session_id
    )

    return handle_ai_reschedule_state_flow(
        db=db,
        request_data=request_data,
        hospital=hospital,
        session_id=session_id,
        chat_history=chat_history,
        ai_understanding=ai_understanding,
        current_state=current_state
    )

def start_cancel_retention_flow(
    db: Session,
    request_data: ChatMessageRequest,
    session_id: str,
    chat_history: str,
    ai_understanding: dict,
):
    """
    First cancellation request: make exactly one professional retention attempt.
    The LLM decides language and wording; backend only records the workflow state.
    No cancellation happens here.
    """
    source = normalize_source(getattr(request_data, "source", "website"))
    whatsapp_number = getattr(request_data, "whatsapp_number", None)

    appointment_id = get_ai_appointment_id(
        ai_understanding,
        request_data.message,
        chat_history,
    )

    patient_phone = ai_understanding.get("patient_phone")
    if source == "whatsapp" and whatsapp_number:
        patient_phone = whatsapp_number

    save_conversation_state(
        db=db,
        hospital_id=request_data.hospital_id,
        session_id=session_id,
        mode="cancel_retention",
        step="offer_reschedule",
        appointment_id=appointment_id,
        patient_phone=patient_phone,
        payload={"retention_offer_made": True},
    )

    return build_chat_response(
        db=db,
        hospital_id=request_data.hospital_id,
        session_id=session_id,
        message=request_data.message,
        answer=(
            "This is the first cancellation request. Do not cancel the appointment yet. "
            "Acknowledge the request professionally, then make one concise non-pushy retention offer: "
            "explain that the appointment can be rescheduled by changing the date, time, or doctor if that is more convenient. "
            "Ask whether the patient would like to reschedule instead or continue with cancellation. "
            "Do not ask for Appointment ID or phone number yet unless they were already supplied; do not claim any cancellation occurred."
        ),
        intent="cancel_retention_offer",
        sources=[],
    )


def handle_cancel_retention_state(
    db: Session,
    request_data: ChatMessageRequest,
    hospital: Hospital,
    session_id: str,
    chat_history: str,
    ai_understanding: dict,
    current_state: dict,
):
    """Handle the patient's decision after the one-time cancellation save attempt."""
    workflow_action = str(ai_understanding.get("workflow_action") or "unclear").strip().lower()
    intent = str(ai_understanding.get("intent") or "unknown").strip().lower()

    # Patient accepts an alternative: preserve any ID/phone already supplied and
    # enter the existing reschedule state machine.
    if workflow_action == "choose_reschedule" or intent == "reschedule_appointment":
        seeded_state = save_conversation_state(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            mode="reschedule",
            step="collecting",
            appointment_id=current_state.get("appointment_id"),
            patient_phone=current_state.get("patient_phone"),
            payload={"came_from_cancel_retention": True},
        )

        return handle_ai_reschedule_state_flow(
            db=db,
            request_data=request_data,
            hospital=hospital,
            session_id=session_id,
            chat_history=chat_history,
            ai_understanding=ai_understanding,
            current_state=seeded_state,
        )

    # Patient clearly insists on cancellation: respect the decision and do not
    # make a second retention attempt. Continue the secure cancellation flow.
    if workflow_action == "proceed_cancel" or intent == "cancel_appointment":
        saved_state = dict(current_state)
        clear_conversation_state(db, request_data.hospital_id, session_id)
        return handle_ai_cancel_flow(
            db=db,
            request_data=request_data,
            session_id=session_id,
            chat_history=chat_history,
            ai_understanding=ai_understanding,
            current_state=saved_state,
        )

    # Ambiguous reply: let the LLM clarify the two choices, still without
    # repeating a canned patient-facing sentence.
    return build_chat_response(
        db=db,
        hospital_id=request_data.hospital_id,
        session_id=session_id,
        message=request_data.message,
        answer=(
            "The cancellation retention offer is still active. Clarify the patient's choice naturally: "
            "would they like to reschedule/change date, time, or doctor, or should cancellation continue? "
            "Do not repeat a sales pitch and do not cancel anything until the choice is clear."
        ),
        intent="cancel_retention_clarify",
        sources=[],
    )



def get_appointment_action_block_reason(appointment: Appointment, action: str) -> Optional[str]:
    """
    Return a backend-enforced reason why an existing appointment cannot be
    modified. The LLM may explain this reason, but it cannot override it.

    Only active future appointments are cancellable/reschedulable.
    """
    action_word = "cancelled" if action == "cancel" else "rescheduled"
    status = str(getattr(appointment, "status", "") or "").strip().lower()

    if status not in {"booked", "confirmed"}:
        if status == "cancelled":
            return "This appointment is already cancelled."
        if status in {"completed", "done"}:
            return "This appointment is already completed."
        if status in {"no_show", "no-show", "noshow"}:
            return "This appointment is already marked as a no-show."
        return f"This appointment is not active (current status: {status or 'unknown'})."

    appointment_date = getattr(appointment, "appointment_date", None)
    if isinstance(appointment_date, str):
        appointment_date = parse_date_value(appointment_date)

    if not appointment_date:
        return f"The appointment date could not be verified, so it cannot be {action_word}."

    today = date.today()
    if appointment_date < today:
        return f"This appointment was on {format_date_for_patient(appointment_date)} and has already passed. Past appointments cannot be {action_word}."

    if appointment_date == today:
        appointment_time = getattr(appointment, "appointment_time", None)
        if isinstance(appointment_time, str):
            appointment_time = parse_time_value(appointment_time)

        if appointment_time:
            try:
                if datetime.combine(appointment_date, appointment_time) <= datetime.now():
                    return f"This appointment was scheduled for {format_time_for_patient(appointment_time)} today and that time has already passed. It cannot be {action_word}."
            except Exception:
                pass

    return None

def handle_ai_cancel_flow(
    db: Session,
    request_data: ChatMessageRequest,
    session_id: str,
    chat_history: str,
    ai_understanding: dict,
    current_state: Optional[dict] = None,
):
    """
    Secure multi-turn cancellation flow.

    The LLM understands the patient's language/meaning, while backend state
    remembers already-supplied verification fields so the patient is not asked
    for them again. No phrase dictionary is used.
    """
    source = normalize_source(getattr(request_data, "source", "website"))
    whatsapp_number = getattr(request_data, "whatsapp_number", None)

    # If the patient changes their mind before cancellation is completed,
    # allow the semantic brain to move into rescheduling without another pitch.
    workflow_action = str(ai_understanding.get("workflow_action") or "").strip().lower()
    intent = str(ai_understanding.get("intent") or "").strip().lower()
    if current_state and (
        workflow_action == "choose_reschedule" or intent == "reschedule_appointment"
    ):
        hospital = db.query(Hospital).filter(Hospital.id == request_data.hospital_id).first()
        seeded_state = save_conversation_state(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            mode="reschedule",
            step="collecting",
            appointment_id=current_state.get("appointment_id"),
            patient_phone=current_state.get("patient_phone"),
            payload={"came_from_cancel_flow": True},
        )
        return handle_ai_reschedule_state_flow(
            db=db,
            request_data=request_data,
            hospital=hospital,
            session_id=session_id,
            chat_history=chat_history,
            ai_understanding=ai_understanding,
            current_state=seeded_state,
        )

    # Merge newly understood values with values already accepted in backend state.
    given_phone = ai_understanding.get("patient_phone")
    if source == "whatsapp" and whatsapp_number:
        given_phone = whatsapp_number
    if not given_phone and current_state:
        given_phone = current_state.get("patient_phone")

    appointment_id = get_ai_appointment_id(
        ai_understanding,
        request_data.message,
        chat_history,
    )
    if not appointment_id and current_state and current_state.get("appointment_id"):
        try:
            appointment_id = int(current_state.get("appointment_id"))
        except Exception:
            appointment_id = None

    # Deterministic value capture for very short numeric replies inside an
    # already-active cancellation workflow. This is value parsing, not a
    # language/phrase list, and prevents replies such as "13" from restarting
    # the cancellation intent flow.
    raw_message = str(request_data.message or "").strip()
    numeric_only = re.sub(r"[^0-9]", "", raw_message)
    state_step = str((current_state or {}).get("step") or "")

    if current_state and current_state.get("mode") == "cancel" and numeric_only:
        if not appointment_id and state_step in {"need_appointment_id", "need_id_and_phone", "collecting"}:
            # Appointment IDs are normally short numeric identifiers. If the
            # value looks like a phone number, leave it for phone capture.
            if len(numeric_only) <= 6:
                try:
                    appointment_id = int(numeric_only)
                except Exception:
                    pass

        if not given_phone and state_step == "need_phone":
            if 7 <= len(numeric_only) <= 15:
                given_phone = numeric_only

        if not given_phone and not appointment_id and state_step == "need_id_and_phone":
            if 7 <= len(numeric_only) <= 15:
                given_phone = numeric_only

    needs_id = not appointment_id
    needs_phone = source != "whatsapp" and not given_phone

    if needs_id or needs_phone:
        if needs_id and needs_phone:
            next_step = "need_id_and_phone"
            instruction = (
                "Cancellation continue karne ke liye sirf Appointment ID aur appointment ke sath registered phone number chahiye. "
                "Jo detail patient pehle de chuka ho usay dobara mat maango."
            )
        elif needs_id:
            next_step = "need_appointment_id"
            instruction = (
                "Phone number mil chuka hai. Cancellation continue karne ke liye ab sirf Appointment ID maango."
            )
        else:
            next_step = "need_phone"
            instruction = (
                f"Appointment ID {appointment_id} mil chuki hai. Ab sirf appointment ke sath registered phone number maango."
            )

        save_conversation_state(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            mode="cancel",
            step=next_step,
            appointment_id=appointment_id,
            patient_phone=given_phone,
            payload={"retention_offer_made": True},
        )

        answer = make_ai_reply(
            user_message=request_data.message,
            base_instruction=instruction,
            reply_type="cancel_need_details",
            chat_history=chat_history,
        )

        return build_chat_response(
            db,
            request_data.hospital_id,
            session_id,
            request_data.message,
            answer,
            "cancel_need_details",
            [],
        )

    appointment, patient = get_appointment_with_patient(
        db,
        request_data.hospital_id,
        appointment_id,
    )

    if not appointment or not patient:
        # Keep verified phone if present, but require a fresh appointment ID.
        save_conversation_state(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            mode="cancel",
            step="need_appointment_id",
            appointment_id=None,
            patient_phone=given_phone,
            payload={"retention_offer_made": True},
        )

        answer = make_ai_reply(
            user_message=request_data.message,
            base_instruction=(
                "Is Appointment ID par record nahi mila. Patient se sirf correct Appointment ID maango; "
                "agar phone pehle mil chuka hai to usay dobara mat maango."
            ),
            reply_type="cancel_not_found",
            chat_history=chat_history,
        )

        return build_chat_response(
            db,
            request_data.hospital_id,
            session_id,
            request_data.message,
            answer,
            "cancel_not_found",
            [],
        )

    if given_phone and not phone_matches_with_lockout(patient, given_phone):
        # Keep the valid appointment ID and ask only for the correct phone.
        save_conversation_state(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            mode="cancel",
            step="need_phone",
            appointment_id=appointment_id,
            patient_phone=None,
            payload={"retention_offer_made": True},
        )

        answer = make_ai_reply(
            user_message=request_data.message,
            base_instruction=(
                f"Appointment ID {appointment_id} mil gayi hai, lekin phone match nahi hua. "
                "Patient se sirf appointment ke sath registered correct phone number maango."
            ),
            reply_type="cancel_phone_mismatch",
            chat_history=chat_history,
        )

        return build_chat_response(
            db,
            request_data.hospital_id,
            session_id,
            request_data.message,
            answer,
            "cancel_phone_mismatch",
            [],
        )

    # Backend business rule: only active future appointments can be cancelled.
    # Never let the LLM override this rule.
    cancel_block_reason = get_appointment_action_block_reason(appointment, "cancel")
    if cancel_block_reason:
        clear_conversation_state(db, request_data.hospital_id, session_id)
        answer = make_ai_reply(
            user_message=request_data.message,
            base_instruction=(
                f"Do not cancel this appointment. Verified backend reason: {cancel_block_reason} "
                "Explain it briefly in the patient's current language/style. Do not ask for ID or phone again, "
                "do not offer rescheduling for a past/completed appointment, and do not claim cancellation occurred."
            ),
            reply_type="cancel_not_allowed",
            chat_history=chat_history,
        )
        return build_chat_response(
            db,
            request_data.hospital_id,
            session_id,
            request_data.message,
            answer,
            "cancel_not_allowed",
            [],
        )

    appointment.status = "cancelled"
    db.commit()
    clear_conversation_state(db, request_data.hospital_id, session_id)

    answer = make_ai_reply(
        user_message=request_data.message,
        base_instruction=(
            f"Appointment ID {appointment.id} successfully cancel ho gayi hai. "
            "Patient ko concise confirmation dein aur unnecessary details dobara na maangein."
        ),
        reply_type="cancel_completed",
        chat_history=chat_history,
    )

    return build_chat_response(
        db,
        request_data.hospital_id,
        session_id,
        request_data.message,
        answer,
        "cancel_completed",
        [],
    )


def handle_ai_status_flow(
    db: Session,
    request_data: ChatMessageRequest,
    session_id: str,
    chat_history: str,
    ai_understanding: dict,
    current_state: Optional[dict] = None,
):
    """
    Stateful appointment-status workflow.

    The LLM understands what the patient supplied, while the backend stores
    already-collected verification details so the patient is not asked for
    the same information again.
    """
    source = normalize_source(getattr(request_data, "source", "website"))
    whatsapp_number = getattr(request_data, "whatsapp_number", None)

    if current_state is None:
        current_state = get_conversation_state(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
        )

    given_phone = ai_understanding.get("patient_phone")

    if source == "whatsapp" and whatsapp_number:
        given_phone = whatsapp_number

    if not given_phone and current_state:
        given_phone = current_state.get("patient_phone")

    appointment_id = get_ai_appointment_id(
        ai_understanding,
        request_data.message,
        chat_history,
    )

    if not appointment_id and current_state and current_state.get("appointment_id"):
        try:
            appointment_id = int(current_state.get("appointment_id"))
        except Exception:
            appointment_id = None

    needs_phone = source != "whatsapp" and not given_phone
    needs_id = not appointment_id

    if needs_id or needs_phone:
        if needs_id and needs_phone:
            step = "need_id_and_phone"
            instruction = (
                "Appointment status check karne ke liye patient se Appointment ID "
                "aur registered phone number maangein. Natural language mein, same "
                "language/style mein jawab dein."
            )
        elif needs_id:
            step = "need_id"
            instruction = (
                "Registered phone number mil chuka hai. Sirf Appointment ID maangein; "
                "phone number dobara na maangein."
            )
        else:
            step = "need_phone"
            instruction = (
                f"Appointment ID {appointment_id} mil chuki hai. Sirf registered phone "
                "number maangein; Appointment ID dobara na maangein."
            )

        save_conversation_state(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            mode="status",
            step=step,
            appointment_id=appointment_id,
            patient_phone=given_phone,
        )

        answer = make_ai_reply(
            user_message=request_data.message,
            base_instruction=instruction,
            reply_type="status_need_details",
            chat_history=chat_history,
        )

        return build_chat_response(
            db, request_data.hospital_id, session_id, request_data.message,
            answer, "status_need_details", []
        )

    appointment, patient = get_appointment_with_patient(
        db, request_data.hospital_id, appointment_id
    )

    if not appointment or not patient:
        # Keep a verified phone if one was supplied, but discard the bad ID so
        # the patient only has to correct the missing/invalid detail.
        save_conversation_state(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            mode="status",
            step="need_id",
            appointment_id=None,
            patient_phone=given_phone,
        )

        answer = make_ai_reply(
            user_message=request_data.message,
            base_instruction=(
                "Is Appointment ID ke sath appointment nahi mili. Patient se sirf "
                "correct Appointment ID maangein. Jo phone number pehle diya gaya hai "
                "usay dobara na maangein."
            ),
            reply_type="status_not_found",
            chat_history=chat_history,
        )

        return build_chat_response(
            db, request_data.hospital_id, session_id, request_data.message,
            answer, "status_not_found", []
        )

    if given_phone and not phone_matches_with_lockout(patient, given_phone):
        save_conversation_state(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            mode="status",
            step="need_phone",
            appointment_id=appointment_id,
            patient_phone=None,
        )

        answer = make_ai_reply(
            user_message=request_data.message,
            base_instruction=(
                f"Appointment ID {appointment_id} mil chuki hai lekin phone number "
                "appointment record se match nahi karta. Sirf correct registered phone "
                "number maangein; Appointment ID dobara na maangein."
            ),
            reply_type="status_phone_mismatch",
            chat_history=chat_history,
        )

        return build_chat_response(
            db, request_data.hospital_id, session_id, request_data.message,
            answer, "status_phone_mismatch", []
        )

    doctor = get_doctor_by_id(
        db, request_data.hospital_id, appointment.doctor_id
    )

    clear_conversation_state(
        db, request_data.hospital_id, session_id
    )

    answer = make_ai_reply(
        user_message=request_data.message,
        base_instruction=(
            "Patient ko appointment status naturally batayein. Ye verified backend "
            "details hain; in mein koi fact add/change na karein:\n"
            f"Appointment ID: {appointment.id}\n"
            f"Patient: {patient.name}\n"
            f"Doctor: {doctor.name if doctor else 'Doctor'}\n"
            f"Date: {format_date_for_patient(appointment.appointment_date)}\n"
            f"Time: {format_time_for_patient(appointment.appointment_time)}\n"
            f"Status: {appointment.status}"
        ),
        reply_type="status_result",
        chat_history=chat_history,
    )

    return build_chat_response(
        db, request_data.hospital_id, session_id, request_data.message,
        answer, "status_result", []
    )


def handle_ai_patient_correction(
    db: Session,
    request_data: ChatMessageRequest,
    session_id: str,
    chat_history: str,
    ai_understanding: dict,
    current_state: Optional[dict] = None,
):
    """
    Secure patient-information correction workflow.

    Security rules:
    1. AI may understand the request, but it never directly authorizes a DB write.
    2. The existing appointment phone must be verified first (or WhatsApp sender number).
    3. Only patient name and patient phone can be changed here.
    4. A proposed value must come from the user's current message, not only from AI output.
    5. Every change requires an explicit YES confirmation before db.commit().
    """
    source = normalize_source(getattr(request_data, "source", "website"))
    whatsapp_number = getattr(request_data, "whatsapp_number", None)
    state_payload = get_state_payload(current_state)

    # --------------------------------------------------------
    # FINAL CONFIRMATION STEP
    # --------------------------------------------------------
    if current_state and current_state.get("step") == "waiting_for_confirmation":
        appointment_id = current_state.get("appointment_id")
        correction_field = normalize_correction_field(state_payload.get("correction_field"))
        proposed_value = state_payload.get("proposed_value")

        workflow_action = str(ai_understanding.get("workflow_action") or "unclear").strip().lower()

        if workflow_action == "cancel_workflow":
            clear_conversation_state(db, request_data.hospital_id, session_id)
            return build_chat_response(
                db=db,
                hospital_id=request_data.hospital_id,
                session_id=session_id,
                message=request_data.message,
                answer="Theek hai, patient information update cancel kar di gayi hai. Koi record change nahi hua.",
                intent="correction_cancelled",
                sources=[],
            )

        if workflow_action != "confirm":
            return build_chat_response(
                db=db,
                hospital_id=request_data.hospital_id,
                session_id=session_id,
                message=request_data.message,
                answer="Update confirm karne ke liye YES likhein, ya cancel karne ke liye NO likhein.",
                intent="correction_waiting_for_confirmation",
                sources=[],
            )

        if not appointment_id or not correction_field or not proposed_value:
            clear_conversation_state(db, request_data.hospital_id, session_id)
            return build_chat_response(
                db=db,
                hospital_id=request_data.hospital_id,
                session_id=session_id,
                message=request_data.message,
                answer="Correction session incomplete tha, is liye koi record update nahi hua. Please correction dobara start karein.",
                intent="correction_session_invalid",
                sources=[],
            )

        appointment, patient = get_appointment_with_patient(
            db, request_data.hospital_id, int(appointment_id)
        )

        if not appointment or not patient:
            clear_conversation_state(db, request_data.hospital_id, session_id)
            return build_chat_response(
                db=db,
                hospital_id=request_data.hospital_id,
                session_id=session_id,
                message=request_data.message,
                answer="Appointment record ab available nahi hai. Koi patient information update nahi hui.",
                intent="correction_appointment_not_found",
                sources=[],
            )

        # Re-check authorization immediately before the DB mutation.
        if source == "whatsapp" and whatsapp_number:
            authorization_ok = phone_matches(patient.phone, whatsapp_number)
        else:
            verified_phone = current_state.get("patient_phone")
            authorization_ok = bool(verified_phone and phone_matches(patient.phone, verified_phone))

        if not authorization_ok:
            clear_conversation_state(db, request_data.hospital_id, session_id)
            return build_chat_response(
                db=db,
                hospital_id=request_data.hospital_id,
                session_id=session_id,
                message=request_data.message,
                answer="Security verification expire ya mismatch ho gayi. Koi record update nahi hua. Please correction dobara start karein.",
                intent="correction_verification_failed",
                sources=[],
            )

        is_valid, clean_value, validation_error = validate_correction_value(
            correction_field, proposed_value
        )
        if not is_valid:
            clear_conversation_state(db, request_data.hospital_id, session_id)
            return build_chat_response(
                db=db,
                hospital_id=request_data.hospital_id,
                session_id=session_id,
                message=request_data.message,
                answer=validation_error or "New value valid nahi hai. Correction dobara start karein.",
                intent="correction_invalid_value",
                sources=[],
            )

        if correction_field == "patient_name":
            if patient.name.strip().lower() == clean_value.strip().lower():
                clear_conversation_state(db, request_data.hospital_id, session_id)
                return build_chat_response(
                    db=db,
                    hospital_id=request_data.hospital_id,
                    session_id=session_id,
                    message=request_data.message,
                    answer="Yehi patient name record me already saved hai. Koi change zaroori nahi tha.",
                    intent="correction_no_change",
                    sources=[],
                )

            patient.name = clean_value
            updated_field = "Patient name"

        elif correction_field == "patient_phone":
            if phone_matches(patient.phone, clean_value):
                clear_conversation_state(db, request_data.hospital_id, session_id)
                return build_chat_response(
                    db=db,
                    hospital_id=request_data.hospital_id,
                    session_id=session_id,
                    message=request_data.message,
                    answer="Yehi phone number record me already saved hai. Koi change zaroori nahi tha.",
                    intent="correction_no_change",
                    sources=[],
                )

            patient.phone = clean_value
            updated_field = "Phone number"

        else:
            clear_conversation_state(db, request_data.hospital_id, session_id)
            return build_chat_response(
                db=db,
                hospital_id=request_data.hospital_id,
                session_id=session_id,
                message=request_data.message,
                answer="Sirf patient name ya phone number correct kiya ja sakta hai.",
                intent="correction_field_not_allowed",
                sources=[],
            )

        db.commit()
        db.refresh(patient)
        clear_conversation_state(db, request_data.hospital_id, session_id)

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=(
                f"{updated_field} successfully update ho gaya hai.\n"
                f"Appointment ID: {appointment.id}\n"
                f"Patient: {patient.name}\n"
                f"Phone: {patient.phone}"
            ),
            intent="correction_completed",
            sources=[],
        )

    # --------------------------------------------------------
    # COLLECT / VERIFY CORRECTION DETAILS
    # --------------------------------------------------------
    appointment_id = (
        current_state.get("appointment_id")
        if current_state and current_state.get("appointment_id")
        else get_ai_appointment_id(ai_understanding, request_data.message, chat_history)
    )

    if not appointment_id:
        save_conversation_state(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            mode="patient_correction",
            step="waiting_for_appointment_id",
            payload=state_payload,
        )
        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer="Correction ke liye Appointment ID bhej dein.",
            intent="correction_need_appointment_id",
            sources=[],
        )

    appointment, patient = get_appointment_with_patient(
        db, request_data.hospital_id, int(appointment_id)
    )

    if not appointment or not patient:
        save_conversation_state(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            mode="patient_correction",
            step="waiting_for_appointment_id",
            payload=state_payload,
        )
        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer="Appointment nahi mili. Correct Appointment ID bhej dein.",
            intent="correction_appointment_not_found",
            sources=[],
        )

    correction_field = normalize_correction_field(
        state_payload.get("correction_field") or ai_understanding.get("correction_field")
    )

    if not correction_field:
        message_lower = normalize_message(request_data.message)
        if "phone" in message_lower or "number" in message_lower or "mobile" in message_lower:
            correction_field = "patient_phone"
        elif "name" in message_lower:
            correction_field = "patient_name"

    if not correction_field:
        save_conversation_state(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            mode="patient_correction",
            step="waiting_for_field",
            appointment_id=appointment.id,
            payload={},
        )
        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer="Aap patient NAME correct karna chahte hain ya PHONE NUMBER?",
            intent="correction_need_field",
            sources=[],
        )

    pending_value = state_payload.get("proposed_value")
    proposed_value = get_proposed_correction_value(
        correction_field=correction_field,
        ai_understanding=ai_understanding,
        message=request_data.message,
        patient=patient,
        pending_value=pending_value,
    )

    # Verify the existing identity before allowing any record change.
    phone_verified, verified_phone, phone_error = verify_patient_phone_for_correction(
        source=source,
        whatsapp_number=whatsapp_number,
        patient=patient,
        message=request_data.message,
        state=current_state,
    )

    if not phone_verified:
        payload = {"correction_field": correction_field, "phone_verified": False}
        if proposed_value:
            payload["proposed_value"] = proposed_value

        save_conversation_state(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            mode="patient_correction",
            step="waiting_for_phone_verification",
            appointment_id=appointment.id,
            patient_phone=None,
            payload=payload,
        )

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=phone_error,
            intent="correction_need_phone_verification",
            sources=[],
        )

    if not proposed_value:
        save_conversation_state(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            mode="patient_correction",
            step="waiting_for_new_value",
            appointment_id=appointment.id,
            patient_phone=verified_phone,
            payload={
                "correction_field": correction_field,
                "phone_verified": True,
            },
        )

        requested_value = "new correct name" if correction_field == "patient_name" else "new phone number"
        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=f"Phone verify ho gaya. Ab {requested_value} bhej dein.",
            intent="correction_need_new_value",
            sources=[],
        )

    is_valid, clean_value, validation_error = validate_correction_value(
        correction_field, proposed_value
    )

    if not is_valid:
        save_conversation_state(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            mode="patient_correction",
            step="waiting_for_new_value",
            appointment_id=appointment.id,
            patient_phone=verified_phone,
            payload={
                "correction_field": correction_field,
                "phone_verified": True,
            },
        )
        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=validation_error,
            intent="correction_invalid_value",
            sources=[],
        )

    if correction_field == "patient_name":
        old_display = patient.name
        new_display = clean_value
    else:
        old_display = patient.phone
        new_display = clean_value

    # Store the proposed value, but DO NOT mutate Patient yet.
    save_conversation_state(
        db=db,
        hospital_id=request_data.hospital_id,
        session_id=session_id,
        mode="patient_correction",
        step="waiting_for_confirmation",
        appointment_id=appointment.id,
        patient_phone=verified_phone,
        payload={
            "correction_field": correction_field,
            "proposed_value": clean_value,
            "phone_verified": True,
        },
    )

    return build_chat_response(
        db=db,
        hospital_id=request_data.hospital_id,
        session_id=session_id,
        message=request_data.message,
        answer=(
            "Please update confirm karein:\n"
            f"Appointment ID: {appointment.id}\n"
            f"Current: {old_display}\n"
            f"New: {new_display}\n"
            "Update karne ke liye YES, cancel karne ke liye NO likhein."
        ),
        intent="correction_waiting_for_confirmation",
        sources=[],
    )


# ============================================================
# AVAILABILITY-ONLY FLOW
# ============================================================
# This flow is separate from booking/reschedule.
# It only answers slot/timing questions and never saves phone/date/time into drafts.


def get_weekday_date_from_message(message: str):
    """English weekday fallback only. Primary weekday understanding comes from the LLM.

    Word boundaries avoid accidental matches such as "mon" inside another word.
    """
    message_lower = normalize_message(message)
    aliases = {
        "monday": "Monday", "mon": "Monday",
        "tuesday": "Tuesday", "tue": "Tuesday",
        "wednesday": "Wednesday", "wed": "Wednesday",
        "thursday": "Thursday", "thu": "Thursday",
        "friday": "Friday", "fri": "Friday",
        "saturday": "Saturday", "sat": "Saturday",
        "sunday": "Sunday", "sun": "Sunday",
    }
    for token, canonical in aliases.items():
        if re.search(rf"\b{re.escape(token)}\b", message_lower):
            return resolve_next_weekday_date(canonical)
    return None


def resolve_availability_date(message: str, ai_understanding: dict):
    return resolve_semantic_date(ai_understanding, message)


def format_slot_list_for_reply(available_slots: list, max_slots: int = 12):
    if not available_slots:
        return "No available slots."

    formatted_slots = []

    for slot in available_slots[:max_slots]:
        parsed_time = parse_time_value(slot)
        formatted_slots.append(format_time_for_patient(parsed_time))

    slots_text = ", ".join(formatted_slots)

    if len(available_slots) > max_slots:
        slots_text += f", and {len(available_slots) - max_slots} more"

    return slots_text


def is_direct_availability_message(message: str, ai_understanding: dict):
    # AI-first: do not use spelling/keyword lists here.
    # The AI understanding layer decides whether this is an availability request.
    intent = ai_understanding.get("intent")

    if intent == "doctor_availability":
        return True

    if ai_understanding.get("availability_query"):
        return True

    return False


def handle_ai_availability_only_flow(
    db: Session,
    request_data: ChatMessageRequest,
    hospital: Hospital,
    session_id: str,
    chat_history: str,
    ai_understanding: dict,
    resume_active_workflow: bool = False,
):
    appointment_date = resolve_availability_date(
        message=request_data.message,
        ai_understanding=ai_understanding
    )

    availability_scope = str(ai_understanding.get("availability_scope") or "unknown").strip()
    requested_view = str(ai_understanding.get("requested_view") or "unknown").strip()

    if availability_scope not in ["unknown", "all_doctors", "specific_doctor", "specialty"]:
        availability_scope = "unknown"

    if requested_view not in ["unknown", "doctor_list", "weekly_timings", "available_slots_by_date", "next_available_slots"]:
        requested_view = "unknown"

    if availability_scope == "unknown":
        if ai_understanding.get("doctor_id") or ai_understanding.get("doctor_name"):
            availability_scope = "specific_doctor"
        elif ai_understanding.get("doctor_specialty"):
            availability_scope = "specialty"
        else:
            availability_scope = "all_doctors"

    if requested_view == "unknown":
        if appointment_date:
            requested_view = "available_slots_by_date"
        elif availability_scope == "all_doctors":
            requested_view = "weekly_timings"
        else:
            requested_view = "next_available_slots"

    # Case 1: user wants all doctors / general doctor availability.
    if availability_scope == "all_doctors":
        if appointment_date:
            slots_context, found_any_slot = build_slots_for_all_doctors(
                db=db,
                hospital_id=request_data.hospital_id,
                appointment_date=appointment_date
            )

            if found_any_slot:
                answer = slots_context + "\nAppointment book karni ho to doctor, time, patient name aur phone number bhej dein."
            else:
                answer = build_no_all_doctor_slots_reply(
                    db=db,
                    hospital_id=request_data.hospital_id,
                    appointment_date=appointment_date
                )

            return build_chat_response(
                db=db,
                hospital_id=request_data.hospital_id,
                session_id=session_id,
                message=request_data.message,
                answer=answer,
                intent="doctor_availability_all_by_date",
                sources=[],
                resume_active_workflow=resume_active_workflow,
            )

        answer = (
            build_appointment_context(
                db=db,
                hospital_id=request_data.hospital_id
            )
            + "\n\nExact available slots dekhne ke liye date/day bhej dein. Example: Monday slots."
        )

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=answer,
            intent="doctor_availability_all_weekly",
            sources=[],
            resume_active_workflow=resume_active_workflow,
        )

    matched_doctor, possible_matches = match_doctor(
        db=db,
        hospital_id=request_data.hospital_id,
        doctor_id=ai_understanding.get("doctor_id"),
        doctor_name=ai_understanding.get("doctor_name"),
        doctor_specialty=ai_understanding.get("doctor_specialty")
    )

    if possible_matches:
        # If user asked by specialty and a date was provided, show slots for all matched doctors.
        if availability_scope == "specialty" and appointment_date:
            lines = [f"Available slots for {format_date_for_patient(appointment_date)}:"]
            found_any_slot = False

            for doctor in possible_matches:
                slots_data = get_available_slots_for_doctor(
                    db=db,
                    hospital_id=request_data.hospital_id,
                    doctor_id=doctor.id,
                    appointment_date=appointment_date
                )

                if not slots_data or not slots_data.get("available_slots"):
                    continue

                found_any_slot = True
                lines.append(f"{doctor.name} - {doctor.specialization}: {format_slot_list_for_reply(slots_data['available_slots'])}")

            if not found_any_slot:
                lines.append(f"Is specialty ke liye {format_date_for_patient(appointment_date)} par koi available appointment slot nahi hai.")
                lines.append("Aap koi aur date ya specialty bhej dein.")

            return build_chat_response(
                db=db,
                hospital_id=request_data.hospital_id,
                session_id=session_id,
                message=request_data.message,
                answer="\n".join(lines),
                intent="doctor_availability_specialty_by_date",
                sources=[],
                resume_active_workflow=resume_active_workflow,
            )

        lines = ["Multiple doctors match hue hain:"]
        for doctor in possible_matches:
            lines.append(f"Doctor ID {doctor.id}: {doctor.name} - {doctor.specialization}")
        lines.append("Slots dekhne ke liye exact Doctor ID ya doctor name bhej dein.")

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer="\n".join(lines),
            intent="doctor_availability_choose_doctor",
            sources=[],
            resume_active_workflow=resume_active_workflow,
        )

    # Use active draft doctor only when the AI says user is asking about a specific doctor but did not repeat the name.
    if not matched_doctor and availability_scope == "specific_doctor":
        active_draft = get_active_appointment_draft(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id
        )

        if active_draft and active_draft.doctor_id:
            matched_doctor = get_doctor_by_id(
                db=db,
                hospital_id=request_data.hospital_id,
                doctor_id=active_draft.doctor_id
            )

    if matched_doctor and appointment_date:
        selected_doctor_context, available_slots = build_slots_for_selected_doctor(
            db=db,
            hospital_id=request_data.hospital_id,
            doctor=matched_doctor,
            appointment_date=appointment_date
        )

        if available_slots:
            answer = (
                f"{matched_doctor.name} ke {format_date_for_patient(appointment_date)} available slots: "
                f"{format_slot_list_for_reply(available_slots)}."
            )
        else:
            answer = (
                f"{matched_doctor.name} ke {format_date_for_patient(appointment_date)} koi available slot nahi hai.\n"
                f"{selected_doctor_context}"
            )

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=answer,
            intent="doctor_availability_result",
            sources=[],
            resume_active_workflow=resume_active_workflow,
        )

    if matched_doctor and not appointment_date:
        # Never present a doctor's recurring working schedule as if every time
        # inside that window were still bookable. Live availability must always
        # come from public_booking_service, which excludes already-booked slots
        # (and same-day expired slots).
        live_slots_context = build_next_available_slots_for_doctor(
            db=db,
            hospital_id=request_data.hospital_id,
            doctor=matched_doctor,
            days_ahead=14,
            max_dates=5
        )

        if requested_view == "weekly_timings":
            recurring_schedule = build_single_doctor_weekly_context(
                db=db,
                hospital_id=request_data.hospital_id,
                doctor=matched_doctor
            )
            answer = (
                "Recurring doctor schedule (reference only; these hours are NOT a list of free appointment slots):\n"
                + recurring_schedule
                + "\n\nLive bookable appointment slots from the backend:\n"
                + live_slots_context
                + "\nOnly offer/select a time from the live bookable slots above."
            )
            response_intent = "doctor_schedule_with_live_availability"
        else:
            answer = (
                live_slots_context
                + "\nOnly offer/select a date and time that appears in the live available slots above."
            )
            response_intent = "doctor_availability_next_slots"

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=answer,
            intent=response_intent,
            sources=[],
            resume_active_workflow=resume_active_workflow,
        )

    # If no doctor is matched but date is available, show all doctors for that date.
    if appointment_date:
        slots_context, found_any_slot = build_slots_for_all_doctors(
            db=db,
            hospital_id=request_data.hospital_id,
            appointment_date=appointment_date
        )

        if found_any_slot:
            answer = slots_context + "\nAppointment book karni ho to doctor, time, patient name aur phone number bhej dein."
        else:
            answer = build_no_all_doctor_slots_reply(
                db=db,
                hospital_id=request_data.hospital_id,
                appointment_date=appointment_date
            )

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=answer,
            intent="doctor_availability_all_by_date",
            sources=[],
            resume_active_workflow=resume_active_workflow,
        )

    # Safe final fallback: show all doctors weekly instead of asking for keywords/name again.
    answer = (
        build_appointment_context(
            db=db,
            hospital_id=request_data.hospital_id
        )
        + "\n\nExact available slots dekhne ke liye date/day bhej dein. Example: Monday slots."
    )

    return build_chat_response(
        db=db,
        hospital_id=request_data.hospital_id,
        session_id=session_id,
        message=request_data.message,
        answer=answer,
        intent="doctor_availability_all_weekly",
        sources=[],
        resume_active_workflow=resume_active_workflow,
    )


def get_medical_safety_answer(emergency: bool = False) -> str:
    if emergency:
        return (
            "This may be a medical emergency. Please contact local emergency services "
            "or go to the nearest emergency department immediately. Do not delay "
            "getting medical care. I cannot diagnose this safely over chat."
        )

    return (
        "I can explain general health information, but I cannot safely provide an individualized diagnosis, "
        "prescription, medicine dose, personal test interpretation, or treatment plan. Please consult a qualified clinician."
    )


def should_block_medical_request(message: str, intent: str) -> bool:
    # Semantic classification is performed by the LLM brain. The backend only
    # enforces the resulting safety class; no patient-language keyword list is used.
    return intent in {"medical_safety", "emergency"}


def get_general_health_information_answer(message: str, chat_history: str = "") -> str:
    # Patient-safe fallback if the LLM provider is unavailable. When the LLM is
    # available, brain_service is allowed to answer general medical education
    # while keeping diagnosis/prescription boundaries.
    return (
        "I can explain general health information and medical concepts, but I cannot diagnose you or prescribe "
        "a medicine/dose here. If your symptoms are severe, sudden, worsening, or you feel very unwell, please "
        "seek professional medical care."
    )

def save_chat_log(
    db: Session,
    hospital_id: int,
    session_id: str,
    message: str,
    answer: str,
    intent: str
):
    chat_log = ChatLog(
        hospital_id=hospital_id,
        session_id=session_id,
        message=message,
        answer=answer,
        intent=intent
    )

    db.add(chat_log)
    db.commit()
    db.refresh(chat_log)

    return chat_log


def _confirmed_booking_reply_matches_record(generated_reply: str, verified_receipt: str) -> bool:
    """Prevent an AI-generated booking receipt from changing a committed appointment ID.

    Natural wording stays model-generated when the model includes the correct ID.
    If the model invents an ID or omits it, use the already-existing verified
    receipt instead. This is validation of a database fact, not intent matching.
    """
    record_id = re.search(
        r"(?im)^\s*appointment\s+id\s*:\s*(\d+)\s*$",
        str(verified_receipt or ""),
    )
    if not record_id:
        return False

    # Accept normal receipt labels while supporting natural generated grammar,
    # e.g. "Appointment ID is 123" and "Your booking number: 123".
    labels = re.findall(
        r"(?i)\b(?:appointment|booking|confirmation|reference)\s*"
        r"(?:id|number|no\.?)?\s*(?:is\s+|[:#-]\s*)?#?(\d+)\b",
        str(generated_reply or ""),
    )
    return bool(labels) and all(int(label) == int(record_id.group(1)) for label in labels)


def build_chat_response(
    db: Session,
    hospital_id: int,
    session_id: str,
    message: str,
    answer: str,
    intent: str,
    sources: Optional[list] = None,
    resume_active_workflow: bool = False,
    safe_fallback_answer: Optional[str] = None,
):
    """
    Single patient-facing response gateway.

    Backend handlers supply validated facts/actions as `answer`. The LLM brain
    turns that authoritative result into natural language while seeing the
    active state and recent conversation, so it does not repeatedly ask for
    information that has already been collected.
    """
    if sources is None:
        sources = []

    recent_chat = get_recent_chat_history(
        db=db,
        hospital_id=hospital_id,
        session_id=session_id,
        limit=int(getattr(settings, "CHAT_CONTEXT_TURNS", 4)),
    )

    active_workflow = compact_conversation_state(
        get_conversation_state(
            db=db,
            hospital_id=hospital_id,
            session_id=session_id,
        )
    )

    try:
        appointment_draft_text = get_current_appointment_draft_text(
            db=db,
            hospital_id=hospital_id,
            session_id=session_id,
        )
    except Exception:
        appointment_draft_text = "No active appointment draft."

    try:
        source_notes = json.dumps(sources, default=str, ensure_ascii=False)
    except Exception:
        source_notes = str(sources)

    # Do not spend a separate LLM request only to classify language.
    # The final patient-facing LLM already sees the patient's current message
    # and recent chat, so it can mirror the language/style in the same call.
    # This preserves LLM-generated replies while reducing quota usage.
    # Keep a known conversational style for tiny ambiguous follow-ups only.
    # Actual full patient messages always determine their own language.
    reply_language_style = (
        patient_memory_service.get_conversation_language(db, hospital_id, session_id)
        if len(str(message or "").strip()) <= 12 else None
    )

    final_answer = brain_service.compose_patient_reply(
        user_message=message,
        authoritative_result=str(answer or "").strip(),
        intent=intent,
        recent_chat=recent_chat,
        active_workflow=active_workflow,
        appointment_draft_text=appointment_draft_text,
        source_notes=source_notes,
        language_style=reply_language_style,
        resume_active_workflow=resume_active_workflow,
    )

    # The booking is already committed. Do not let a fluent but incorrect AI
    # confirmation imply another appointment ID, or omit the reference needed
    # to identify the real booking. Prefer the verified receipt in that case.
    if (
        intent in {"appointment_confirmed", "reschedule_completed"}
        and safe_fallback_answer
        and final_answer
        and not _confirmed_booking_reply_matches_record(final_answer, safe_fallback_answer)
    ):
        final_answer = str(safe_fallback_answer).strip()

    if not final_answer:
        # Clinical escalation must remain available even when ALL LLM providers
        # are down. These are safety fallbacks, not keyword-based chat replies.
        # Keep the original conversational state and do not create an appointment.
        if intent == "emergency":
            final_answer = get_medical_safety_answer(emergency=True)
        elif intent == "medical_safety":
            final_answer = get_medical_safety_answer(emergency=False)
        else:
            # An already-committed database mutation must not appear to fail
            # because the final wording LLM is unavailable.
            final_answer = (
                str(safe_fallback_answer or "").strip()
                or "I'm having trouble generating the response right now. Please try again."
            )

    save_chat_log(
        db=db,
        hospital_id=hospital_id,
        session_id=session_id,
        message=message,
        answer=final_answer,
        intent=intent
    )

    return {
        "message": message,
        "answer": final_answer,
        "intent": intent,
        "sources": sources,
        "session_id": session_id
    }

def get_recent_chat_history(
    db: Session,
    hospital_id: int,
    session_id: str,
    limit: Optional[int] = None,
):
    if limit is None:
        limit = int(getattr(settings, "CHAT_CONTEXT_TURNS", 4))
    limit = max(1, min(int(limit), 10))
    chat_logs = (
        db.query(ChatLog)
        .filter(
            ChatLog.hospital_id == hospital_id,
            ChatLog.session_id == session_id
        )
        .order_by(ChatLog.created_at.desc())
        .limit(limit)
        .all()
    )

    chat_logs = list(reversed(chat_logs))

    if not chat_logs:
        return ""

    # Stored text may contain newlines, forged "Assistant:" headers, or prompt
    # injection. Serialize each turn as quoted data before passing it to an LLM.
    # The router/reply generator can re-clip this without breaking role boundaries.
    max_chars = max(800, int(getattr(settings, "CHAT_CONTEXT_MAX_CHARS", 3200)))
    return conversation_context_service.render_history(
        [(log.message, log.answer) for log in chat_logs], max_chars
    )


def safe_text(value, max_length: int = 300):
    if value is None:
        return ""

    text = str(value).strip()

    if len(text) > max_length:
        return text[:max_length].strip() + "..."

    return text


def format_time_for_patient(value):
    if not value:
        return ""

    try:
        return value.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return str(value)


def format_date_for_patient(value):
    if not value:
        return ""

    try:
        return value.strftime("%A, %d %B %Y")
    except Exception:
        return str(value)


def parse_date_value(value):
    if not value:
        return None

    try:
        return date.fromisoformat(str(value).strip())
    except Exception:
        return None


def parse_time_value(value):
    if not value:
        return None

    clean_value = str(value).strip()

    formats = [
        "%H:%M:%S",
        "%H:%M",
        "%I:%M %p",
        "%I %p"
    ]

    for time_format in formats:
        try:
            return datetime.strptime(clean_value, time_format).time()
        except Exception:
            pass

    return None


def time_to_slot_string(value):
    if not value:
        return ""

    if isinstance(value, str):
        parsed_time = parse_time_value(value)

        if parsed_time:
            return parsed_time.strftime("%H:%M:%S")

        return value

    try:
        return value.strftime("%H:%M:%S")
    except Exception:
        return str(value)


def _get_reception_contact_line(db: Session, hospital_id: int) -> str:
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if hospital and hospital.phone:
        return f" Hospital contact: {safe_text(hospital.phone, 80)}."

    contact = (
        db.query(EmergencyContact)
        .filter(
            EmergencyContact.hospital_id == hospital_id,
            EmergencyContact.is_active == True,
        )
        .order_by(EmergencyContact.id.asc())
        .first()
    )
    if contact and contact.phone_number:
        return f" Contact: {safe_text(contact.phone_number, 80)}."
    return ""


def build_unconfirmed_hospital_answer(db: Session, hospital_id: int) -> str:
    return (
        "I don't have confirmed information about that in the hospital records available to me. "
        "Please contact reception to confirm."
        + _get_reception_contact_line(db, hospital_id)
    )


def _patient_doctor_name(name: str) -> str:
    clean_name = safe_text(name, 150).strip()
    if re.match(r"^dr\.?\s+", clean_name, flags=re.IGNORECASE):
        return clean_name
    return f"Dr. {clean_name}"


def _semantic_record_id(question: str, target: str, rows: list, label_getter, details_getter=None):
    candidates = []
    for row in rows:
        candidates.append(
            {
                "id": row.id,
                "label": label_getter(row),
                "details": details_getter(row) if details_getter else "",
            }
        )
    return brain_service.select_candidate_id(
        question=question,
        target=target,
        candidates=candidates,
    )


def build_verified_hospital_answer(
    db: Session,
    hospital_id: int,
    message: str,
    intent: str = "",
    ai_understanding: Optional[dict] = None,
):
    """
    Retrieve hospital facts using the semantic plan produced by the LLM brain.

    The LLM selects WHAT the patient is asking for and, when necessary, selects
    only from backend-provided record IDs. The backend still returns the actual
    stored values. There are no expanding patient-language keyword dictionaries
    in this retrieval path.
    """
    plan = ai_understanding or {}
    target = str(plan.get("information_target") or "unknown").strip()
    field = str(plan.get("requested_field") or "unknown").strip()
    search_text = str(plan.get("search_text") or "").strip()

    if target == "unknown" and intent == "doctor_information":
        target = "doctor"
    elif target == "unknown" and intent == "hospital_information":
        target = "policy_or_faq"

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()

    if target == "hospital_profile" and hospital:
        values = {
            "name": ("Hospital", hospital.name),
            "address": ("Address", hospital.address),
            "phone": ("Phone", hospital.phone),
            "email": ("Email", hospital.email),
        }

        if field in values:
            label, value = values[field]
            if value:
                return f"{label}: {safe_text(value, 400)}", [f"hospital.{field}"]
            return None, []

        lines = []
        sources = []
        for key in ("name", "address", "phone", "email"):
            label, value = values[key]
            if value:
                lines.append(f"{label}: {safe_text(value, 400)}")
                sources.append(f"hospital.{key}")
        return ("\n".join(lines), sources) if lines else (None, [])

    if target == "doctor":
        doctors = (
            db.query(Doctor)
            .filter(Doctor.hospital_id == hospital_id, Doctor.is_active == True)
            .order_by(Doctor.id.asc())
            .all()
        )
        if not doctors:
            return None, []

        if field == "list" and not (plan.get("doctor_id") or plan.get("doctor_name") or search_text):
            lines = []
            for doctor in doctors[:30]:
                fee_text = f" | Fee: Rs. {doctor.consultation_fee:g}" if doctor.consultation_fee is not None else ""
                lines.append(
                    f"Doctor ID {doctor.id}: {_patient_doctor_name(doctor.name)} | "
                    f"{safe_text(doctor.specialization, 150)}{fee_text}"
                )
            return "\n".join(lines), ["doctors"]

        selected = None
        doctor_id = plan.get("doctor_id")
        if doctor_id:
            try:
                selected = next((d for d in doctors if d.id == int(doctor_id)), None)
            except Exception:
                selected = None

        if selected is None:
            lookup_question = search_text or str(plan.get("doctor_name") or "").strip() or message
            selected_id = _semantic_record_id(
                lookup_question,
                "doctor",
                doctors,
                lambda row: row.name,
                lambda row: row.specialization,
            )
            selected = next((d for d in doctors if d.id == selected_id), None)

        if selected is None:
            return None, []

        doctor_name = _patient_doctor_name(selected.name)
        if field == "fee":
            return f"{doctor_name} consultation fee: Rs. {selected.consultation_fee:g}", [f"doctor:{selected.id}"]
        if field == "specialty":
            return f"{doctor_name} specialty: {safe_text(selected.specialization, 150)}", [f"doctor:{selected.id}"]
        if field == "phone" and selected.phone:
            return f"{doctor_name} contact: {safe_text(selected.phone, 80)}", [f"doctor:{selected.id}"]
        if field in {"schedule", "availability"}:
            return build_single_doctor_weekly_context(db, hospital_id, selected), [f"doctor:{selected.id}", "schedules"]

        fee_text = f"Rs. {selected.consultation_fee:g}" if selected.consultation_fee is not None else "not recorded"
        return (
            f"{doctor_name} | Specialty: {safe_text(selected.specialization, 150)} | Consultation fee: {fee_text}",
            [f"doctor:{selected.id}"],
        )

    if target == "department":
        rows = (
            db.query(Department)
            .filter(Department.hospital_id == hospital_id, Department.is_active == True)
            .order_by(Department.id.asc())
            .all()
        )
        if field == "list" or not search_text:
            if not rows:
                return None, []
            return "\n".join(f"- {safe_text(row.name, 160)}" for row in rows[:40]), ["departments"]

        selected_id = _semantic_record_id(
            search_text or message,
            "department",
            rows,
            lambda row: row.name,
            lambda row: row.description or "",
        )
        row = next((item for item in rows if item.id == selected_id), None)
        if not row:
            return None, []
        detail = safe_text(row.description, 1000) if row.description else "No additional description is recorded."
        return f"{safe_text(row.name, 160)}: {detail}", [f"department:{row.id}"]

    if target == "service":
        rows = (
            db.query(HospitalService)
            .filter(HospitalService.hospital_id == hospital_id, HospitalService.is_active == True)
            .order_by(HospitalService.id.asc())
            .all()
        )
        if field == "list" or not search_text:
            if not rows:
                return None, []
            return "\n".join(f"- {safe_text(row.name, 160)}" for row in rows[:40]), ["services"]

        selected_id = _semantic_record_id(
            search_text or message,
            "hospital service",
            rows,
            lambda row: row.name,
            lambda row: row.description or "",
        )
        row = next((item for item in rows if item.id == selected_id), None)
        if not row:
            return None, []
        detail = safe_text(row.description, 1000) if row.description else "This service is listed as available."
        return f"{safe_text(row.name, 160)}: {detail}", [f"service:{row.id}"]

    if target == "lab_test":
        rows = (
            db.query(LabTest)
            .filter(LabTest.hospital_id == hospital_id, LabTest.is_active == True)
            .order_by(LabTest.id.asc())
            .all()
        )
        if field == "list" or not search_text:
            if not rows:
                return None, []
            return "\n".join(f"- {safe_text(row.name, 160)}" for row in rows[:40]), ["lab_tests"]

        selected_id = _semantic_record_id(
            search_text or message,
            "lab test",
            rows,
            lambda row: row.name,
            lambda row: row.description or "",
        )
        row = next((item for item in rows if item.id == selected_id), None)
        if not row:
            return None, []

        if field == "price":
            if row.price is None:
                return None, []
            return f"{safe_text(row.name, 160)} price: Rs. {row.price:g}", [f"lab_test:{row.id}"]
        if field == "report_time":
            if not row.report_time:
                return None, []
            return f"{safe_text(row.name, 160)} report time: {safe_text(row.report_time, 120)}", [f"lab_test:{row.id}"]
        if field == "sample_type":
            if not row.sample_type:
                return None, []
            return f"{safe_text(row.name, 160)} sample type: {safe_text(row.sample_type, 120)}", [f"lab_test:{row.id}"]

        details = [f"Test: {safe_text(row.name, 160)}"]
        if row.price is not None:
            details.append(f"Price: Rs. {row.price:g}")
        if row.sample_type:
            details.append(f"Sample: {safe_text(row.sample_type, 120)}")
        if row.report_time:
            details.append(f"Report time: {safe_text(row.report_time, 120)}")
        if row.description:
            details.append(safe_text(row.description, 600))
        return " | ".join(details), [f"lab_test:{row.id}"]

    if target == "emergency_contact":
        rows = (
            db.query(EmergencyContact)
            .filter(EmergencyContact.hospital_id == hospital_id, EmergencyContact.is_active == True)
            .order_by(EmergencyContact.id.asc())
            .all()
        )
        if not rows:
            return None, []
        lines = []
        for row in rows[:20]:
            title = safe_text(row.title or row.contact_type or "Contact", 160)
            phone = safe_text(row.phone_number, 80) if row.phone_number else ""
            if phone:
                lines.append(f"{title}: {phone}")
        return ("\n".join(lines), ["emergency_contacts"]) if lines else (None, [])

    if target in {"policy_or_faq", "unknown"}:
        try:
            faqs = faq_service.get_active_faqs(db=db, hospital_id=hospital_id)
        except Exception:
            faqs = []

        if faqs:
            selected_id = brain_service.select_candidate_id(
                question=message,
                target="hospital FAQ/policy",
                candidates=[
                    {
                        "id": faq.id,
                        "label": safe_text(faq.question, 500),
                        "details": safe_text(faq.category, 150),
                    }
                    for faq in faqs[:60]
                ],
            )
            faq = next((item for item in faqs if item.id == selected_id), None)
            if faq:
                return safe_text(faq.answer, 1500), [f"faq:{faq.id}"]

    return None, []

def build_hospital_context(db: Session, hospital_id: int, message: str):
    lines = []

    hospital = (
        db.query(Hospital)
        .filter(Hospital.id == hospital_id)
        .first()
    )

    if hospital:
        lines.append(f"Hospital name: {safe_text(hospital.name)}")

    faq_answer = None

    try:
        faq_answer = faq_service.find_best_faq_answer(
            db=db,
            hospital_id=hospital_id,
            message=message
        )
    except Exception:
        faq_answer = None

    if faq_answer:
        lines.append("Relevant FAQ answer:")
        lines.append(safe_text(faq_answer, 800))

    doctors = (
        db.query(Doctor)
        .filter(
            Doctor.hospital_id == hospital_id,
            Doctor.is_active == True
        )
        .order_by(Doctor.name.asc())
        .limit(30)
        .all()
    )

    if doctors:
        lines.append("Available doctors:")

        for doctor in doctors:
            fee_text = ""

            if doctor.consultation_fee is not None:
                fee_text = f", fee Rs. {doctor.consultation_fee}"

            lines.append(
                f"- {safe_text(doctor.name)} | {safe_text(doctor.specialization)} | ID {doctor.id}{fee_text}"
            )

    departments = (
        db.query(Department)
        .filter(
            Department.hospital_id == hospital_id,
            Department.is_active == True
        )
        .order_by(Department.name.asc())
        .limit(30)
        .all()
    )

    if departments:
        lines.append("Departments:")

        for department in departments:
            lines.append(f"- {safe_text(department.name)}: {safe_text(department.description)}")

    services = (
        db.query(HospitalService)
        .filter(
            HospitalService.hospital_id == hospital_id,
            HospitalService.is_active == True
        )
        .order_by(HospitalService.name.asc())
        .limit(30)
        .all()
    )

    if services:
        lines.append("Hospital services:")

        for service in services:
            lines.append(f"- {safe_text(service.name)}: {safe_text(service.description)}")

    lab_tests = (
        db.query(LabTest)
        .filter(
            LabTest.hospital_id == hospital_id,
            LabTest.is_active == True
        )
        .order_by(LabTest.name.asc())
        .limit(40)
        .all()
    )

    if lab_tests:
        lines.append("Lab tests:")

        for lab_test in lab_tests:
            details = []

            if lab_test.price is not None:
                details.append(f"price Rs. {lab_test.price}")

            if lab_test.sample_type:
                details.append(f"sample {lab_test.sample_type}")

            if lab_test.report_time:
                details.append(f"report time {lab_test.report_time}")

            details_text = ""

            if details:
                details_text = " (" + ", ".join(details) + ")"

            lines.append(f"- {safe_text(lab_test.name)}{details_text}")

    contacts = (
        db.query(EmergencyContact)
        .filter(
            EmergencyContact.hospital_id == hospital_id,
            EmergencyContact.is_active == True
        )
        .order_by(EmergencyContact.title.asc())
        .limit(20)
        .all()
    )

    if contacts:
        lines.append("Emergency/reception contacts:")

        for contact in contacts:
            lines.append(
                f"- {safe_text(contact.title)}: {safe_text(contact.phone_number)} {safe_text(contact.description)}"
            )

    if not lines:
        return "No hospital database context available."

    return "\n".join(lines)


def make_ai_reply(
    user_message: str,
    base_instruction: str,
    reply_type: str,
    chat_history: str = "",
    extra_context: str = ""
):
    """
    Return an authoritative backend result/directive. The central LLM brain in
    build_chat_response is the only layer that writes patient-facing prose.
    """
    return str(base_instruction or "").strip()


def is_ai_failure_answer(answer: str) -> bool:
    if not answer:
        return True

    answer_lower = str(answer).lower().strip()

    failure_prefixes = [
        "provider_error:",
        "ai service is temporarily unavailable"
    ]

    for prefix in failure_prefixes:
        if answer_lower.startswith(prefix):
            return True

    return False


def get_active_appointment_draft(db: Session, hospital_id: int, session_id: str):
    return (
        db.query(AppointmentDraft)
        .filter(
            AppointmentDraft.hospital_id == hospital_id,
            AppointmentDraft.session_id == session_id,
            AppointmentDraft.status == "collecting"
        )
        .order_by(AppointmentDraft.updated_at.desc())
        .first()
    )


def get_or_create_appointment_draft(
    db: Session,
    hospital_id: int,
    session_id: str,
    source: str,
    whatsapp_number: Optional[str] = None
):
    draft = get_active_appointment_draft(
        db=db,
        hospital_id=hospital_id,
        session_id=session_id
    )

    if draft:
        if source == "whatsapp" and whatsapp_number:
            draft.source = source
            draft.whatsapp_number = whatsapp_number
            draft.patient_phone = whatsapp_number
            draft.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(draft)

        return draft

    draft = AppointmentDraft(
        hospital_id=hospital_id,
        session_id=session_id,
        source=source,
        whatsapp_number=whatsapp_number,
        patient_phone=whatsapp_number if source == "whatsapp" and whatsapp_number else None,
        status="collecting",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )

    db.add(draft)
    db.commit()
    db.refresh(draft)

    return draft


def save_draft(db: Session, draft: AppointmentDraft):
    draft.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(draft)

    return draft


def build_current_draft_text(draft: AppointmentDraft):
    doctor_text = ""

    if draft.doctor_id:
        doctor_text = f"doctor_id={draft.doctor_id}"

    if draft.doctor_name_text:
        doctor_text = f"{doctor_text} doctor_text={draft.doctor_name_text}".strip()

    return (
        f"source={draft.source}\n"
        f"whatsapp_number={draft.whatsapp_number}\n"
        f"{doctor_text}\n"
        f"appointment_date={draft.appointment_date}\n"
        f"appointment_time={draft.appointment_time}\n"
        f"patient_name={draft.patient_name}\n"
        f"patient_phone={draft.patient_phone}"
    )


def get_sorted_schedules(db: Session, hospital_id: int, doctor_id: int):
    schedules = (
        db.query(Schedule)
        .filter(
            Schedule.hospital_id == hospital_id,
            Schedule.doctor_id == doctor_id,
            Schedule.is_active == True
        )
        .all()
    )

    schedules = sorted(
        schedules,
        key=lambda schedule: DAY_ORDER.get(schedule.day_of_week, 99)
    )

    return schedules


def build_single_doctor_weekly_context(
    db: Session,
    hospital_id: int,
    doctor: Doctor
):
    lines = []

    fee_text = ""

    if doctor.consultation_fee is not None:
        fee_text = f"Fee: Rs. {doctor.consultation_fee}"

    lines.append(
        f"Doctor ID {doctor.id}: {doctor.name} - {doctor.specialization} {fee_text}".strip()
    )

    schedules = get_sorted_schedules(
        db=db,
        hospital_id=hospital_id,
        doctor_id=doctor.id
    )

    if schedules:
        lines.append("Weekly timings:")

        for schedule in schedules:
            lines.append(
                f"- {schedule.day_of_week}: "
                f"{format_time_for_patient(schedule.start_time)} to {format_time_for_patient(schedule.end_time)}, "
                f"slot duration {schedule.slot_duration_minutes} minutes"
            )
    else:
        lines.append("No weekly schedule added yet.")

    return "\n".join(lines)


def build_appointment_context(db: Session, hospital_id: int):
    """
    Build booking choices from doctors who can actually be scheduled.

    A doctor is shown only when:
    - the doctor is active, and
    - at least one active weekly Schedule record exists.

    This keeps unscheduled doctors out of the LLM context entirely, so the
    conversational model cannot present them as booking options or say
    "schedule unavailable" for them.
    """
    scheduled_rows = (
        db.query(Schedule.doctor_id)
        .filter(
            Schedule.hospital_id == hospital_id,
            Schedule.is_active == True
        )
        .distinct()
        .all()
    )
    scheduled_doctor_ids = {row[0] for row in scheduled_rows}

    if not scheduled_doctor_ids:
        return "No doctors with an active appointment schedule are available right now."

    doctors = (
        db.query(Doctor)
        .filter(
            Doctor.hospital_id == hospital_id,
            Doctor.is_active == True,
            Doctor.id.in_(scheduled_doctor_ids)
        )
        .order_by(Doctor.name.asc())
        .all()
    )

    if not doctors:
        return "No doctors with an active appointment schedule are available right now."

    lines = ["Doctors currently available for appointment booking:"]

    for doctor in doctors:
        lines.append(
            build_single_doctor_weekly_context(
                db=db,
                hospital_id=hospital_id,
                doctor=doctor
            )
        )

    return "\n".join(lines)


def clean_doctor_text(value):
    if not value:
        return ""

    text = str(value).lower().strip()
    text = text.replace("dr.", "")
    text = text.replace("dr ", "")
    text = text.replace("doctor", "")
    text = text.replace(".", "")
    text = " ".join(text.split())

    return text


def match_doctor(
    db: Session,
    hospital_id: int,
    doctor_id: Optional[int] = None,
    doctor_name: Optional[str] = None,
    doctor_specialty: Optional[str] = None
):
    doctors = (
        db.query(Doctor)
        .filter(
            Doctor.hospital_id == hospital_id,
            Doctor.is_active == True
        )
        .order_by(Doctor.name.asc())
        .all()
    )

    if doctor_id:
        for doctor in doctors:
            if doctor.id == doctor_id:
                return doctor, []

    name_text = clean_doctor_text(doctor_name)
    specialty_text = clean_doctor_text(doctor_specialty)

    matches = []

    if name_text:
        for doctor in doctors:
            doctor_name_clean = clean_doctor_text(doctor.name)

            if name_text == doctor_name_clean:
                return doctor, []

            if name_text in doctor_name_clean or doctor_name_clean in name_text:
                matches.append(doctor)

    if not matches and specialty_text:
        for doctor in doctors:
            doctor_specialization_clean = clean_doctor_text(doctor.specialization)

            if specialty_text in doctor_specialization_clean or doctor_specialization_clean in specialty_text:
                matches.append(doctor)

    unique_matches = []

    for doctor in matches:
        if doctor not in unique_matches:
            unique_matches.append(doctor)

    if len(unique_matches) == 1:
        return unique_matches[0], []

    return None, unique_matches


def get_available_slots_for_doctor(
    db: Session,
    hospital_id: int,
    doctor_id: int,
    appointment_date: date
):
    try:
        return public_booking_service.get_available_slots(
            db=db,
            hospital_id=hospital_id,
            doctor_id=doctor_id,
            appointment_date=appointment_date
        )
    except Exception:
        return None


def build_slots_for_selected_doctor(
    db: Session,
    hospital_id: int,
    doctor: Doctor,
    appointment_date: date
):
    slots_data = get_available_slots_for_doctor(
        db=db,
        hospital_id=hospital_id,
        doctor_id=doctor.id,
        appointment_date=appointment_date
    )

    lines = [
        f"Doctor: {doctor.name}",
        f"Specialty: {doctor.specialization}",
        f"Date: {format_date_for_patient(appointment_date)}"
    ]

    if not slots_data or not slots_data.get("available_slots"):
        lines.append("No available slots on this date.")
        lines.append("Weekly schedule:")

        schedules = get_sorted_schedules(
            db=db,
            hospital_id=hospital_id,
            doctor_id=doctor.id
        )

        if schedules:
            for schedule in schedules:
                lines.append(
                    f"- {schedule.day_of_week}: "
                    f"{format_time_for_patient(schedule.start_time)} to {format_time_for_patient(schedule.end_time)}"
                )
        else:
            lines.append("- No weekly schedule added yet.")

        return "\n".join(lines), []

    available_slots = slots_data["available_slots"]

    lines.append("Available slots:")

    for slot in available_slots:
        parsed_time = parse_time_value(slot)
        lines.append(f"- {format_time_for_patient(parsed_time)}")

    return "\n".join(lines), available_slots


def build_slots_for_all_doctors(
    db: Session,
    hospital_id: int,
    appointment_date: date
):
    doctors = (
        db.query(Doctor)
        .filter(
            Doctor.hospital_id == hospital_id,
            Doctor.is_active == True
        )
        .order_by(Doctor.name.asc())
        .all()
    )

    lines = [
        f"Available appointment slots for {format_date_for_patient(appointment_date)}:"
    ]

    found_any_slot = False

    for doctor in doctors:
        slots_data = get_available_slots_for_doctor(
            db=db,
            hospital_id=hospital_id,
            doctor_id=doctor.id,
            appointment_date=appointment_date
        )

        if not slots_data or not slots_data.get("available_slots"):
            continue

        found_any_slot = True
        lines.append(f"{doctor.name} - {doctor.specialization}:")

        for slot in slots_data["available_slots"]:
            parsed_time = parse_time_value(slot)
            lines.append(f"- {format_time_for_patient(parsed_time)}")

    if not found_any_slot:
        lines.append(f"No doctor has an available appointment slot on {format_date_for_patient(appointment_date)}.")

    return "\n".join(lines), found_any_slot


def build_next_available_date_options_for_all_doctors(
    db: Session,
    hospital_id: int,
    start_date: Optional[date] = None,
    excluded_date: Optional[date] = None,
    max_dates: int = 3,
    days_ahead: int = 21
):
    search_start = start_date or date.today()

    if search_start < date.today():
        search_start = date.today()

    lines = ["Next available appointment options:"]
    found_dates = 0

    for day_offset in range(0, days_ahead + 1):
        target_date = search_start + timedelta(days=day_offset)

        if excluded_date and target_date == excluded_date:
            continue

        slots_context, found_any_slot, _ = build_slots_for_all_doctors_for_reschedule(
            db=db,
            hospital_id=hospital_id,
            appointment_date=target_date
        )

        if not found_any_slot:
            continue

        found_dates += 1
        lines.append("")
        lines.append(slots_context)

        if found_dates >= max_dates:
            break

    if found_dates == 0:
        lines.append("Next available dates me bhi free doctor slot nahi mila.")

    lines.append("")
    lines.append("In options me se doctor/date/time choose kar dein. Agar in ke ilawa koi date chahiye to woh date bhej dein.")

    return "\n".join(lines), found_dates > 0


def build_no_all_doctor_slots_reply(
    db: Session,
    hospital_id: int,
    appointment_date: date,
    action_hint: str = "appointment"
):
    slots_context, _ = build_slots_for_all_doctors(
        db=db,
        hospital_id=hospital_id,
        appointment_date=appointment_date
    )

    next_options, found_options = build_next_available_date_options_for_all_doctors(
        db=db,
        hospital_id=hospital_id,
        start_date=appointment_date,
        excluded_date=appointment_date,
        max_dates=3,
        days_ahead=21
    )

    if found_options:
        return slots_context + "\n\n" + next_options

    return slots_context + "\nAap koi aur date bhej dein, main us date ke available doctors check kar dunga."


def get_ai_excluded_doctor_id(db: Session, hospital_id: int, ai_understanding: dict):
    """
    Uses the AI understanding result to exclude a doctor when the user asks for alternatives.
    This is semantic and not tied to one fixed sentence.
    """
    if not ai_understanding or not (ai_understanding.get("doctor_exclusion") or ai_understanding.get("doctor_alternative_request")):
        return None

    excluded_id = ai_understanding.get("excluded_doctor_id") or ai_understanding.get("doctor_id")

    if excluded_id:
        try:
            return int(excluded_id)
        except Exception:
            pass

    excluded_name = ai_understanding.get("excluded_doctor_name") or ai_understanding.get("doctor_name")

    if excluded_name:
        matched_doctor, possible_matches = match_doctor(
            db=db,
            hospital_id=hospital_id,
            doctor_name=excluded_name
        )
        if matched_doctor:
            return matched_doctor.id
        if possible_matches and len(possible_matches) == 1:
            return possible_matches[0].id

    return None


def build_slots_for_all_doctors_for_reschedule(
    db: Session,
    hospital_id: int,
    appointment_date: date,
    excluded_doctor_id: Optional[int] = None
):
    doctors = (
        db.query(Doctor)
        .filter(
            Doctor.hospital_id == hospital_id,
            Doctor.is_active == True
        )
        .order_by(Doctor.name.asc())
        .all()
    )

    lines = [
        f"Available doctors and slots for {format_date_for_patient(appointment_date)}:"
    ]

    found_any_slot = False
    available_by_doctor = {}

    for doctor in doctors:
        if excluded_doctor_id and doctor.id == excluded_doctor_id:
            continue

        slots_data = get_available_slots_for_doctor(
            db=db,
            hospital_id=hospital_id,
            doctor_id=doctor.id,
            appointment_date=appointment_date
        )

        if not slots_data or not slots_data.get("available_slots"):
            continue

        found_any_slot = True
        available_by_doctor[doctor.id] = slots_data.get("available_slots", [])
        lines.append(f"Doctor ID {doctor.id}: {doctor.name} - {doctor.specialization}")

        formatted_slots = []
        for slot in slots_data["available_slots"]:
            parsed_time = parse_time_value(slot)
            formatted_slots.append(format_time_for_patient(parsed_time))

        lines.append("Slots: " + ", ".join(formatted_slots))

    if not found_any_slot:
        lines.append(f"No doctor has an available appointment slot on {format_date_for_patient(appointment_date)}.")

    return "\n".join(lines), found_any_slot, available_by_doctor


def build_next_available_slots_for_doctor(
    db: Session,
    hospital_id: int,
    doctor: Doctor,
    days_ahead: int = 14,
    max_dates: int = 5
):
    lines = [
        f"Next available slots for {doctor.name}:"
    ]

    found_dates = 0

    for day_offset in range(0, days_ahead + 1):
        target_date = date.today() + timedelta(days=day_offset)

        slots_data = get_available_slots_for_doctor(
            db=db,
            hospital_id=hospital_id,
            doctor_id=doctor.id,
            appointment_date=target_date
        )

        if not slots_data or not slots_data.get("available_slots"):
            continue

        found_dates += 1

        lines.append(f"{format_date_for_patient(target_date)}:")

        for slot in slots_data["available_slots"]:
            parsed_time = parse_time_value(slot)
            lines.append(f"- {format_time_for_patient(parsed_time)}")

        if found_dates >= max_dates:
            break

    if found_dates == 0:
        lines.append("No free slots found in the next 14 days.")

    return "\n".join(lines)


def apply_ai_extraction_to_draft(
    db: Session,
    draft: AppointmentDraft,
    extraction: dict
):
    doctor_name = extraction.get("doctor_name")
    doctor_specialty = extraction.get("doctor_specialty")
    doctor_id = extraction.get("doctor_id")

    matched_doctor = None
    possible_matches = []

    if doctor_name or doctor_specialty or doctor_id:
        matched_doctor, possible_matches = match_doctor(
            db=db,
            hospital_id=draft.hospital_id,
            doctor_id=doctor_id,
            doctor_name=doctor_name,
            doctor_specialty=doctor_specialty
        )

        if matched_doctor:
            draft.doctor_id = matched_doctor.id
            draft.doctor_name_text = matched_doctor.name
        elif doctor_name:
            draft.doctor_name_text = doctor_name

    extracted_date = parse_date_value(extraction.get("appointment_date"))

    if extracted_date:
        draft.appointment_date = extracted_date

    extracted_time = parse_time_value(extraction.get("appointment_time"))

    if extracted_time:
        draft.appointment_time = extracted_time

    patient_name = extraction.get("patient_name")

    if patient_name:
        draft.patient_name = str(patient_name).strip()

    patient_phone = extraction.get("patient_phone")

    if patient_phone:
        valid_phone = normalize_booking_phone(patient_phone)
        if valid_phone:
            draft.patient_phone = valid_phone

    if draft.source == "whatsapp" and draft.whatsapp_number:
        valid_whatsapp_phone = normalize_booking_phone(draft.whatsapp_number)
        draft.patient_phone = valid_whatsapp_phone

    # Clean up any invalid phone that may already exist in an older/stale draft.
    if draft.patient_phone and not normalize_booking_phone(draft.patient_phone):
        draft.patient_phone = None

    save_draft(db, draft)

    return matched_doctor, possible_matches


def get_doctor_by_id(db: Session, hospital_id: int, doctor_id: int):
    return (
        db.query(Doctor)
        .filter(
            Doctor.id == doctor_id,
            Doctor.hospital_id == hospital_id,
            Doctor.is_active == True
        )
        .first()
    )


def get_missing_booking_fields(draft: AppointmentDraft):
    missing = []

    if not draft.doctor_id:
        missing.append("doctor")

    if not draft.appointment_date:
        missing.append("date")

    if not draft.appointment_time:
        missing.append("time")

    if not draft.patient_name:
        missing.append("patient name")

    if not draft.patient_phone:
        missing.append("phone number")

    return missing


def find_patient_by_phone(db: Session, hospital_id: int, patient_phone: str):
    if not patient_phone:
        return None

    return (
        db.query(Patient)
        .filter(
            Patient.hospital_id == hospital_id,
            Patient.phone == patient_phone
        )
        .first()
    )


def find_existing_appointment_for_reschedule(
    db: Session,
    draft: AppointmentDraft
):
    if not draft.patient_phone:
        return None, []

    patient = find_patient_by_phone(
        db=db,
        hospital_id=draft.hospital_id,
        patient_phone=draft.patient_phone
    )

    if not patient:
        return None, []

    query = (
        db.query(Appointment)
        .filter(
            Appointment.hospital_id == draft.hospital_id,
            Appointment.patient_id == patient.id,
            Appointment.status.in_(["booked", "confirmed"])
        )
    )

    if draft.doctor_id:
        query = query.filter(Appointment.doctor_id == draft.doctor_id)

    appointments = (
        query
        .order_by(
            Appointment.appointment_date.asc(),
            Appointment.appointment_time.asc()
        )
        .all()
    )

    if not appointments:
        return None, []

    if draft.appointment_date:
        same_date_appointments = []

        for appointment in appointments:
            if appointment.appointment_date == draft.appointment_date:
                same_date_appointments.append(appointment)

        if len(same_date_appointments) == 1:
            return same_date_appointments[0], appointments

        if len(same_date_appointments) > 1:
            return None, same_date_appointments

    if len(appointments) == 1:
        return appointments[0], appointments

    return None, appointments


def try_reschedule_existing_appointment_from_draft(
    db: Session,
    draft: AppointmentDraft
):
    if not draft.doctor_id:
        return {"handled": False}

    if not draft.appointment_date:
        return {"handled": False}

    if not draft.appointment_time:
        return {"handled": False}

    if not draft.patient_phone:
        return {"handled": False}

    existing_appointment, matching_appointments = find_existing_appointment_for_reschedule(
        db=db,
        draft=draft
    )

    if not existing_appointment and len(matching_appointments) > 1:
        return {
            "handled": True,
            "success": False,
            "reason": "multiple_active_appointments",
            "matching_appointments": matching_appointments
        }

    if not existing_appointment:
        return {"handled": False}

    doctor = get_doctor_by_id(
        db=db,
        hospital_id=draft.hospital_id,
        doctor_id=draft.doctor_id
    )

    if not doctor:
        return {
            "handled": True,
            "success": False,
            "reason": "doctor_not_found"
        }

    old_date = existing_appointment.appointment_date
    old_time = existing_appointment.appointment_time

    selected_time_string = time_to_slot_string(draft.appointment_time)

    selected_doctor_context, available_slots = build_slots_for_selected_doctor(
        db=db,
        hospital_id=draft.hospital_id,
        doctor=doctor,
        appointment_date=draft.appointment_date
    )

    if (
        old_date == draft.appointment_date
        and old_time == draft.appointment_time
    ):
        return {
            "handled": True,
            "success": False,
            "reason": "same_slot",
            "appointment": existing_appointment,
            "doctor": doctor,
            "context": selected_doctor_context
        }

    if selected_time_string not in available_slots:
        return {
            "handled": True,
            "success": False,
            "reason": "selected_slot_not_available",
            "appointment": existing_appointment,
            "doctor": doctor,
            "context": selected_doctor_context
        }

    public_booking_service.ensure_active_slot_unique_index(db)

    existing_appointment.doctor_id = draft.doctor_id
    existing_appointment.appointment_date = draft.appointment_date
    existing_appointment.appointment_time = draft.appointment_time

    try:
        db.commit()
        db.refresh(existing_appointment)
    except IntegrityError:
        db.rollback()
        # Another request won this slot after our availability check. Convert
        # the database race into the same clean business result used by normal
        # slot conflicts; never leak SQL details.
        latest_context, _ = build_slots_for_selected_doctor(
            db=db,
            hospital_id=draft.hospital_id,
            doctor=doctor,
            appointment_date=draft.appointment_date
        )
        return {
            "handled": True,
            "success": False,
            "reason": "selected_slot_not_available",
            "appointment": existing_appointment,
            "doctor": doctor,
            "context": latest_context
        }

    draft.status = "completed"
    draft.updated_at = datetime.utcnow()
    db.commit()

    return {
        "handled": True,
        "success": True,
        "appointment": existing_appointment,
        "doctor": doctor,
        "old_date": old_date,
        "old_time": old_time
    }


def find_exact_active_appointment_for_draft(db: Session, draft: AppointmentDraft):
    """Return the already-booked appointment represented by this draft, if any.

    This is the idempotency guard for chat retries. A response-generation/provider
    failure can happen AFTER the database has committed successfully. If the
    patient/browser retries the same booking, the assistant must recognize the
    existing appointment as success instead of reporting its own slot as
    unavailable.
    """
    if not (
        draft.doctor_id
        and draft.appointment_date
        and draft.appointment_time
        and draft.patient_phone
    ):
        return None

    patient = (
        db.query(Patient)
        .filter(
            Patient.hospital_id == draft.hospital_id,
            Patient.phone == str(draft.patient_phone).strip(),
        )
        .first()
    )
    if not patient:
        return None

    return (
        db.query(Appointment)
        .filter(
            Appointment.hospital_id == draft.hospital_id,
            Appointment.doctor_id == draft.doctor_id,
            Appointment.patient_id == patient.id,
            Appointment.appointment_date == draft.appointment_date,
            Appointment.appointment_time == draft.appointment_time,
            Appointment.status.in_(["booked", "confirmed"]),
        )
        .order_by(Appointment.id.desc())
        .first()
    )


def _booking_success_fallback(appointment, doctor_name: str, patient_name: str, patient_phone: str) -> str:
    """Fact-only emergency wording used only if all response LLMs are unavailable."""
    return (
        "Appointment confirmed successfully.\n"
        f"Appointment ID: {appointment.id}\n"
        f"Patient: {patient_name}\n"
        f"Phone: {patient_phone}\n"
        f"Doctor: {doctor_name}\n"
        f"Date: {format_date_for_patient(appointment.appointment_date)}\n"
        f"Time: {format_time_for_patient(appointment.appointment_time)}\n"
        f"Status: {appointment.status}"
    )


def book_appointment_from_draft(db: Session, draft: AppointmentDraft):
    request_data = PublicBookAppointmentRequest(
        hospital_id=draft.hospital_id,
        doctor_id=draft.doctor_id,
        patient_name=draft.patient_name,
        patient_phone=draft.patient_phone,
        patient_email=None,
        appointment_date=draft.appointment_date,
        appointment_time=draft.appointment_time,
        reason=None
    )

    result = public_booking_service.book_public_appointment(
        db=db,
        request_data=request_data
    )

    draft.status = "completed"
    draft.updated_at = datetime.utcnow()
    db.commit()

    return result


def update_extraction_flags_from_message(message: str, extraction: dict):
    # These semantic flags come from the LLM brain. Do not re-classify natural
    # language here with growing keyword lists.
    extraction["availability_query"] = bool(extraction.get("availability_query"))
    extraction["date_was_mentioned"] = bool(extraction.get("date_was_mentioned"))
    extraction["time_was_mentioned"] = bool(extraction.get("time_was_mentioned"))

    if extraction.get("availability_query") and not extraction.get("date_was_mentioned"):
        # Prevent a date copied from old context from being treated as a newly
        # selected date. The brain is instructed to set date_was_mentioned only
        # when the patient actually selected/reaffirmed one in this turn.
        extraction["appointment_date"] = None

    return extraction

def handle_reschedule_result(
    db: Session,
    request_data: ChatMessageRequest,
    session_id: str,
    chat_history: str,
    draft: AppointmentDraft,
    reschedule_result: dict
):
    if reschedule_result.get("success"):
        appointment = reschedule_result.get("appointment")
        doctor = reschedule_result.get("doctor")

        base_instruction = (
            "Appointment rescheduled successfully.\n"
            f"Appointment ID: {appointment.id}\n"
            f"Patient: {draft.patient_name}\n"
            f"Phone: {draft.patient_phone}\n"
            f"Doctor: {doctor.name}\n"
            f"Old Date: {format_date_for_patient(reschedule_result.get('old_date'))}\n"
            f"Old Time: {format_time_for_patient(reschedule_result.get('old_time'))}\n"
            f"New Date: {format_date_for_patient(appointment.appointment_date)}\n"
            f"New Time: {format_time_for_patient(appointment.appointment_time)}\n"
            f"Status: {appointment.status}\n"
            "Appointment ID save kar lein."
        )

        answer = make_ai_reply(
            user_message=request_data.message,
            base_instruction=base_instruction,
            reply_type="appointment_rescheduled",
            chat_history=chat_history
        )

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=answer,
            intent="appointment_rescheduled",
            sources=[]
        )

    reason = reschedule_result.get("reason")

    if reason == "multiple_active_appointments":
        matching_appointments = reschedule_result.get("matching_appointments", [])

        lines = [
            "Multiple active appointments found for this phone number."
        ]

        for appointment in matching_appointments:
            appointment_doctor = get_doctor_by_id(
                db=db,
                hospital_id=request_data.hospital_id,
                doctor_id=appointment.doctor_id
            )

            doctor_name = "Doctor"

            if appointment_doctor:
                doctor_name = appointment_doctor.name

            lines.append(
                f"- Appointment ID {appointment.id}: {doctor_name}, "
                f"{format_date_for_patient(appointment.appointment_date)}, "
                f"{format_time_for_patient(appointment.appointment_time)}"
            )

        lines.append("Jis appointment ko change karna hai us ka Appointment ID bhej dein.")

        answer = make_ai_reply(
            user_message=request_data.message,
            base_instruction="\n".join(lines),
            reply_type="reschedule_multiple_appointments",
            chat_history=chat_history
        )

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=answer,
            intent="reschedule_multiple_appointments",
            sources=[]
        )

    if reason == "same_slot":
        appointment = reschedule_result.get("appointment")
        doctor = reschedule_result.get("doctor")

        answer = make_ai_reply(
            user_message=request_data.message,
            base_instruction=(
                "The appointment is already on the selected slot.\n"
                f"Appointment ID: {appointment.id}\n"
                f"Doctor: {doctor.name}\n"
                f"Date: {format_date_for_patient(appointment.appointment_date)}\n"
                f"Time: {format_time_for_patient(appointment.appointment_time)}\n"
                "Change karna ho to available slots me se koi different time bhej dein."
            ),
            reply_type="reschedule_same_slot",
            chat_history=chat_history
        )

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=answer,
            intent="reschedule_same_slot",
            sources=[]
        )

    if reason == "selected_slot_not_available":
        answer = make_ai_reply(
            user_message=request_data.message,
            base_instruction=(
                "Selected new slot is not available.\n"
                f"{reschedule_result.get('context')}\n"
                "Available slots me se koi new time choose kar dein."
            ),
            reply_type="reschedule_slot_not_available",
            chat_history=chat_history
        )

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=answer,
            intent="reschedule_slot_not_available",
            sources=[]
        )

    answer = make_ai_reply(
        user_message=request_data.message,
        base_instruction=(
            "Appointment change nahi ho saki. Details check karke dobara bhej dein."
        ),
        reply_type="reschedule_failed",
        chat_history=chat_history
    )

    return build_chat_response(
        db=db,
        hospital_id=request_data.hospital_id,
        session_id=session_id,
        message=request_data.message,
        answer=answer,
        intent="reschedule_failed",
        sources=[]
    )


def handle_appointment_booking_flow(
    db: Session,
    request_data: ChatMessageRequest,
    hospital: Hospital,
    session_id: str,
    chat_history: str,
    ai_understanding: Optional[dict] = None
):
    source = normalize_source(getattr(request_data, "source", "website"))
    whatsapp_number = getattr(request_data, "whatsapp_number", None)

    if source == "whatsapp" and whatsapp_number:
        whatsapp_number = str(whatsapp_number).strip()
    else:
        whatsapp_number = None

    draft = get_or_create_appointment_draft(
        db=db,
        hospital_id=request_data.hospital_id,
        session_id=session_id,
        source=source,
        whatsapp_number=whatsapp_number
    )

    appointment_context = build_appointment_context(
        db=db,
        hospital_id=request_data.hospital_id
    )

    if ai_understanding:
        extraction = ai_understanding_to_appointment_extraction(ai_understanding, request_data.message)
    else:
        extraction = llm_service.extract_appointment_details_ai(
            user_message=request_data.message,
            current_draft=build_current_draft_text(draft),
            appointment_context=appointment_context
        )

        extraction = update_extraction_flags_from_message(
            message=request_data.message,
            extraction=extraction
        )

    # Deterministic booking-field capture:
    # A phone number supplied while a booking draft is active is booking data. Do not depend
    # on the LLM intent/entity extraction for this simple structured field.
    if not draft.patient_phone:
        current_message_phone = extract_phone_from_current_message(request_data.message)
        if current_message_phone and 7 <= len(current_message_phone) <= 15:
            extraction["patient_phone"] = current_message_phone

    if extraction.get("cancel_draft"):
        draft.status = "cancelled"
        draft.updated_at = datetime.utcnow()
        db.commit()

        answer = make_ai_reply(
            user_message=request_data.message,
            base_instruction="Appointment booking flow has been cancelled.",
            reply_type="appointment_cancel_draft",
            chat_history=chat_history
        )

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=answer,
            intent="appointment_draft_cancelled",
            sources=[]
        )

    matched_doctor, possible_matches = apply_ai_extraction_to_draft(
        db=db,
        draft=draft,
        extraction=extraction
    )

    if extraction.get("availability_query") and not extraction.get("date_was_mentioned"):
        draft.appointment_date = None
        draft.appointment_time = None
        save_draft(db, draft)

    if possible_matches:
        match_lines = ["Multiple matching doctors found:"]

        for doctor in possible_matches:
            fee_text = ""

            if doctor.consultation_fee is not None:
                fee_text = f", fee Rs. {doctor.consultation_fee}"

            match_lines.append(
                f"- Doctor ID {doctor.id}: {doctor.name} - {doctor.specialization}{fee_text}"
            )

        base_instruction = (
            "\n".join(match_lines)
            + "\nJis doctor ke sath appointment chahiye us ka Doctor ID ya name bhej dein."
        )

        answer = make_ai_reply(
            user_message=request_data.message,
            base_instruction=base_instruction,
            reply_type="appointment_choose_doctor",
            chat_history=chat_history,
            extra_context=appointment_context
        )

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=answer,
            intent="appointment_choose_doctor",
            sources=[]
        )

    if extraction.get("availability_query") and draft.doctor_id and not draft.appointment_date:
        doctor = get_doctor_by_id(
            db=db,
            hospital_id=request_data.hospital_id,
            doctor_id=draft.doctor_id
        )

        if doctor:
            next_slots_context = build_next_available_slots_for_doctor(
                db=db,
                hospital_id=request_data.hospital_id,
                doctor=doctor,
                days_ahead=14,
                max_dates=5
            )

            if source == "whatsapp" and draft.patient_phone:
                final_line = (
                    "Exact date, time aur patient name bhej dein."
                )
            else:
                final_line = (
                    "Exact date, time, patient name aur phone number bhej dein."
                )

            answer = make_ai_reply(
                user_message=request_data.message,
                base_instruction=(
                    next_slots_context
                    + "\n"
                    + final_line
                ),
                reply_type="doctor_availability_without_date",
                chat_history=chat_history
            )

            return build_chat_response(
                db=db,
                hospital_id=request_data.hospital_id,
                session_id=session_id,
                message=request_data.message,
                answer=answer,
                intent="doctor_availability_without_date",
                sources=[]
            )

    if not draft.appointment_date:
        if draft.doctor_id:
            doctor = get_doctor_by_id(
                db=db,
                hospital_id=request_data.hospital_id,
                doctor_id=draft.doctor_id
            )

            if doctor:
                selected_doctor_context = build_single_doctor_weekly_context(
                    db=db,
                    hospital_id=request_data.hospital_id,
                    doctor=doctor
                )

                if source == "whatsapp" and draft.patient_phone:
                    final_line = (
                        "Appointment date aur patient name bhej dein."
                    )
                else:
                    final_line = (
                        "Appointment date, patient name aur phone number bhej dein."
                    )

                answer = make_ai_reply(
                    user_message=request_data.message,
                    base_instruction=(
                        selected_doctor_context
                        + "\n"
                        + final_line
                    ),
                    reply_type="appointment_selected_doctor_need_date",
                    chat_history=chat_history
                )

                return build_chat_response(
                    db=db,
                    hospital_id=request_data.hospital_id,
                    session_id=session_id,
                    message=request_data.message,
                    answer=answer,
                    intent="appointment_selected_doctor_need_date",
                    sources=[]
                )

        # Do not turn the conversation into a long form. The LLM should guide
        # the patient one decision at a time and never ask again for values the
        # active draft already contains.
        final_line = (
            "Guide the patient to the next booking decision only. "
            "From the doctors listed above, ask which doctor they prefer; "
            "if they do not know a doctor, let them state the specialty they need. "
            "Do not request date, time, name, and phone all at once."
        )

        base_instruction = appointment_context + "\n\n" + final_line

        answer = make_ai_reply(
            user_message=request_data.message,
            base_instruction=base_instruction,
            reply_type="appointment_start",
            chat_history=chat_history,
            extra_context=appointment_context
        )

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=answer,
            intent="appointment_start",
            sources=[]
        )

    if draft.appointment_date < date.today():
        draft.appointment_date = None
        draft.appointment_time = None
        save_draft(db, draft)

        answer = make_ai_reply(
            user_message=request_data.message,
            base_instruction=(
                "Past date par appointment book nahi ho sakti. Future date choose kar dein."
            ),
            reply_type="appointment_past_date",
            chat_history=chat_history
        )

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=answer,
            intent="appointment_past_date",
            sources=[]
        )

    if not draft.doctor_id:
        slots_context, found_any_slot = build_slots_for_all_doctors(
            db=db,
            hospital_id=request_data.hospital_id,
            appointment_date=draft.appointment_date
        )

        if found_any_slot:
            if source == "whatsapp" and draft.patient_phone:
                final_line = (
                    "Doctor ID/name, time aur patient name bhej dein."
                )
            else:
                final_line = (
                    "Doctor ID/name, time, patient name aur phone number bhej dein."
                )
        else:
            base_instruction = build_no_all_doctor_slots_reply(
                db=db,
                hospital_id=request_data.hospital_id,
                appointment_date=draft.appointment_date
            )
            answer = make_ai_reply(
                user_message=request_data.message,
                base_instruction=base_instruction,
                reply_type="appointment_no_slots_by_date",
                chat_history=chat_history,
                extra_context=appointment_context
            )

            return build_chat_response(
                db=db,
                hospital_id=request_data.hospital_id,
                session_id=session_id,
                message=request_data.message,
                answer=answer,
                intent="appointment_no_slots_by_date",
                sources=[]
            )

        base_instruction = slots_context + "\n" + final_line

        answer = make_ai_reply(
            user_message=request_data.message,
            base_instruction=base_instruction,
            reply_type="appointment_slots_by_date",
            chat_history=chat_history,
            extra_context=appointment_context
        )

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=answer,
            intent="appointment_slots_by_date",
            sources=[]
        )

    doctor = get_doctor_by_id(
        db=db,
        hospital_id=request_data.hospital_id,
        doctor_id=draft.doctor_id
    )

    if not doctor:
        draft.doctor_id = None
        draft.doctor_name_text = None
        save_draft(db, draft)

        answer = make_ai_reply(
            user_message=request_data.message,
            base_instruction=(
                "Selected doctor abhi available nahi hai. Available doctors me se Doctor ID ya name choose kar dein."
            ),
            reply_type="appointment_doctor_unavailable",
            chat_history=chat_history,
            extra_context=appointment_context
        )

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=answer,
            intent="appointment_doctor_unavailable",
            sources=[]
        )

    selected_doctor_context, available_slots = build_slots_for_selected_doctor(
        db=db,
        hospital_id=request_data.hospital_id,
        doctor=doctor,
        appointment_date=draft.appointment_date
    )

    if not available_slots:
        draft.appointment_time = None
        save_draft(db, draft)

        answer = make_ai_reply(
            user_message=request_data.message,
            base_instruction=(
                selected_doctor_context
                + "\nIs doctor ke is date par free slots nahi hain. Weekly schedule me se koi aur date choose kar dein."
            ),
            reply_type="appointment_no_slots",
            chat_history=chat_history
        )

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=answer,
            intent="appointment_no_slots",
            sources=[]
        )

    if not draft.appointment_time:
        missing = get_missing_booking_fields(draft)
        missing_text = ", ".join(missing)

        base_instruction = (
            selected_doctor_context
            + f"\nMissing details bhej dein: {missing_text}."
        )

        if source == "whatsapp" and draft.patient_phone:
            base_instruction += ""

        answer = make_ai_reply(
            user_message=request_data.message,
            base_instruction=base_instruction,
            reply_type="appointment_choose_time",
            chat_history=chat_history
        )

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=answer,
            intent="appointment_choose_time",
            sources=[]
        )

    selected_time_string = time_to_slot_string(draft.appointment_time)

    # Idempotent replay guard: the exact same booking may already exist because
    # the DB commit succeeded but the LLM response failed/timed out. In that case
    # the slot is naturally absent from available_slots, but it belongs to this
    # same patient/draft and must be reported as confirmed, not unavailable.
    existing_exact_appointment = find_exact_active_appointment_for_draft(db, draft)
    if existing_exact_appointment:
        draft.status = "completed"
        draft.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(existing_exact_appointment)

        base_instruction = (
            "This appointment is already confirmed in the database. Treat this as an idempotent retry, not a failed booking.\n"
            f"Appointment ID: {existing_exact_appointment.id}\n"
            f"Patient: {draft.patient_name}\n"
            f"Phone: {draft.patient_phone}\n"
            f"Doctor: {doctor.name}\n"
            f"Date: {format_date_for_patient(existing_exact_appointment.appointment_date)}\n"
            f"Time: {format_time_for_patient(existing_exact_appointment.appointment_time)}\n"
            f"Status: {existing_exact_appointment.status}\n"
            "Tell the patient the appointment is confirmed. Do not ask for confirmation again."
        )

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=base_instruction,
            intent="appointment_confirmed",
            sources=[],
            safe_fallback_answer=_booking_success_fallback(
                existing_exact_appointment,
                doctor.name,
                draft.patient_name,
                draft.patient_phone,
            ),
        )

    if selected_time_string not in available_slots:
        draft.appointment_time = None
        save_draft(db, draft)

        base_instruction = (
            f"{format_time_for_patient(parse_time_value(selected_time_string))} slot is not available.\n"
            + selected_doctor_context
            + "\nAvailable slots me se koi time choose kar dein."
        )

        answer = make_ai_reply(
            user_message=request_data.message,
            base_instruction=base_instruction,
            reply_type="appointment_slot_not_available",
            chat_history=chat_history
        )

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=answer,
            intent="appointment_slot_not_available",
            sources=[]
        )

    missing = get_missing_booking_fields(draft)

    if missing:
        missing_text = ", ".join(missing)

        base_instruction = (
            f"{doctor.name} ka {format_time_for_patient(draft.appointment_time)} slot "
            f"{format_date_for_patient(draft.appointment_date)} ko available hai.\n"
            f"Missing details bhej dein: {missing_text}."
        )

        if source == "whatsapp" and draft.patient_phone:
            base_instruction += ""

        answer = make_ai_reply(
            user_message=request_data.message,
            base_instruction=base_instruction,
            reply_type="appointment_missing_details",
            chat_history=chat_history
        )

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=answer,
            intent="appointment_missing_details",
            sources=[]
        )

    # IMPORTANT WORKFLOW BOUNDARY:
    # This is the NEW-APPOINTMENT workflow. It must never mutate an existing
    # appointment merely because the supplied phone belongs to an existing
    # patient or because that patient already has another appointment.
    #
    # Existing appointments are changed only through the explicit reschedule
    # workflow. The booking service may reuse an existing Patient record, but it
    # must create a new Appointment record here.
    try:
        booking_result = book_appointment_from_draft(
            db=db,
            draft=draft
        )

        base_instruction = (
            "Appointment confirmed successfully.\n"
            f"Appointment ID: {booking_result.get('appointment_id')}\n"
            f"Patient: {draft.patient_name}\n"
            f"Phone: {draft.patient_phone}\n"
            f"Doctor: {booking_result.get('doctor_name')}\n"
            f"Date: {format_date_for_patient(draft.appointment_date)}\n"
            f"Time: {format_time_for_patient(draft.appointment_time)}\n"
            f"Status: {booking_result.get('status')}\n"
            "Appointment ID save kar lein."
        )

        answer = make_ai_reply(
            user_message=request_data.message,
            base_instruction=base_instruction,
            reply_type="appointment_confirmed",
            chat_history=chat_history
        )

        booked_appointment = (
            db.query(Appointment)
            .filter(
                Appointment.id == booking_result.get("appointment_id"),
                Appointment.hospital_id == request_data.hospital_id,
            )
            .first()
        )

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=answer,
            intent="appointment_confirmed",
            sources=[],
            safe_fallback_answer=(
                _booking_success_fallback(
                    booked_appointment,
                    booking_result.get("doctor_name") or doctor.name,
                    draft.patient_name,
                    draft.patient_phone,
                )
                if booked_appointment
                else (
                    "Appointment confirmed successfully.\n"
                    f"Appointment ID: {booking_result.get('appointment_id')}\n"
                    f"Doctor: {booking_result.get('doctor_name') or doctor.name}\n"
                    f"Date: {format_date_for_patient(draft.appointment_date)}\n"
                    f"Time: {format_time_for_patient(draft.appointment_time)}\n"
                    f"Status: {booking_result.get('status')}"
                )
            ),
        )

    except Exception as error:
        # Convert every internal exception to a stable application error. Raw
        # SQL/provider/stack-trace text must never reach the patient or the LLM.
        try:
            db.rollback()
        except Exception:
            pass

        info = error_service.classify_exception(error)
        if info.clear_selected_time:
            draft.appointment_time = None
            save_draft(db, draft)

        selected_doctor_context, available_slots = build_slots_for_selected_doctor(
            db=db,
            hospital_id=request_data.hospital_id,
            doctor=doctor,
            appointment_date=draft.appointment_date
        )

        verified_context = selected_doctor_context if info.code in {"SLOT_TAKEN", "DATABASE_CONFLICT"} else ""
        answer = make_ai_reply(
            user_message=request_data.message,
            base_instruction=error_service.build_llm_directive(info, verified_context=verified_context),
            reply_type="appointment_booking_failed",
            chat_history=chat_history
        )

        fallback = info.patient_message
        if verified_context:
            fallback += "\n" + verified_context

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=answer,
            intent="appointment_booking_failed",
            sources=[],
            safe_fallback_answer=fallback,
        )


def get_chat_logs(db: Session, hospital_id: Optional[int] = None):
    query = db.query(ChatLog)

    if hospital_id is not None:
        query = query.filter(ChatLog.hospital_id == hospital_id)

    return query.order_by(ChatLog.created_at.desc()).all()


def handle_active_workflow_side_question(
    db: Session,
    request_data: ChatMessageRequest,
    hospital: Hospital,
    session_id: str,
    chat_history: str,
    ai_understanding: dict,
):
    """Answer a temporary read-only question without discarding workflow state.

    The LLM decides semantically whether the turn is a side question. This
    function only retrieves/validates facts and leaves the existing state/draft
    untouched. The final LLM reply is explicitly told to resume afterward.
    """
    intent = str(ai_understanding.get("intent") or "unknown")
    if intent not in {
        "greeting", "thanks", "general_question", "general_health_info",
        "doctor_information", "hospital_information", "doctor_availability",
    }:
        return None

    message = request_data.message.strip()

    if intent == "doctor_availability":
        # Read-only availability never changes the pending booking/cancellation.
        # The existing availability handler validates live slots in the DB.
        return handle_ai_availability_only_flow(
            db=db, request_data=request_data, hospital=hospital,
            session_id=session_id, chat_history=chat_history,
            ai_understanding=ai_understanding,
            resume_active_workflow=True,
        )

    if intent in {"doctor_information", "hospital_information"}:
        side_answer, side_sources = build_verified_hospital_answer(
            db=db,
            hospital_id=request_data.hospital_id,
            message=message,
            intent=intent,
            ai_understanding=ai_understanding,
        )

        if not side_answer:
            side_answer, side_sources = rag_service.build_grounded_document_answer(
                db=db,
                hospital_id=request_data.hospital_id,
                question=message,
                max_results=2,
            )

        if not side_answer:
            side_answer = build_unconfirmed_hospital_answer(
                db=db,
                hospital_id=request_data.hospital_id,
            )
            side_sources = []

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=side_answer,
            intent=intent,
            sources=side_sources,
            resume_active_workflow=True,
        )

    if intent == "general_health_info":
        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=get_general_health_information_answer(message, chat_history),
            intent="general_health_info",
            sources=[],
            resume_active_workflow=True,
        )

    if intent in {"general_question", "greeting", "thanks"}:
        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=(
                "Answer the patient's current conversational question naturally. "
                "Do not invent any hospital-specific fact."
            ),
            intent=intent,
            sources=[],
            resume_active_workflow=True,
        )

    return None


def _discard_unfinished_draft(db: Session, draft: Optional[AppointmentDraft]):
    """Abandon only the in-progress draft; never alter a real appointment."""
    if draft is not None and str(draft.status or "").lower() == "collecting":
        draft.status = "cancelled"
        draft.updated_at = datetime.utcnow()
        db.commit()


def _task_mode(intent: str) -> Optional[str]:
    """Map explicit LLM intent to its backend state-machine mode."""
    return {
        "reschedule_appointment": "reschedule",
        "cancel_appointment": "cancel",
        "appointment_status": "status",
        "correct_patient_info": "patient_correction",
    }.get(str(intent or ""))


def _handle_chat_message_impl(db: Session, request_data: ChatMessageRequest):
    hospital = (
        db.query(Hospital)
        .filter(Hospital.id == request_data.hospital_id)
        .first()
    )

    if not hospital:
        raise ValueError("Hospital not found")

    message = request_data.message.strip()
    session_id = normalize_session_id(getattr(request_data, "session_id", "default"))

    if not message:
        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer="Please apna message type kar dein.",
            intent="empty_message",
            sources=[]
        )

    chat_history = get_recent_chat_history(
        db=db,
        hospital_id=request_data.hospital_id,
        session_id=session_id,
        limit=int(getattr(settings, "CHAT_CONTEXT_TURNS", 4))
    )

    ai_understanding = get_ai_message_understanding(
        db=db,
        request_data=request_data,
        hospital=hospital,
        session_id=session_id,
        chat_history=chat_history
    )

    # Do not pretend an LLM/provider failure means the patient was unclear.
    # If the semantic brain is unavailable, return a transparent temporary
    # service message rather than routing through `unknown` and asking the
    # patient to repeat themselves.
    if not bool(ai_understanding.get("_brain_available", True)):
        failure_answer = (
            "The AI assistant is temporarily unavailable, so I couldn't safely understand your request. "
            "Please try again in a moment."
        )
        save_chat_log(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=failure_answer,
            intent="ai_service_unavailable",
        )
        return {
            "message": request_data.message,
            "answer": failure_answer,
            "intent": "ai_service_unavailable",
            "sources": [],
            "session_id": session_id,
        }

    intent = ai_understanding.get("intent", "unknown")
    confidence = ai_understanding.get("confidence", 0.0)

    # Only language preference is persisted; do not activate automatic memory
    # recording of names, phones, symptoms, medical history, or appointments.
    patient_memory_service.remember_conversation_language(
        db, request_data.hospital_id, session_id,
        ai_understanding.get("language_style"), message,
    )

    # Medical safety must outrank ALL active booking/cancellation workflows.
    # Otherwise emergency symptoms can be misread as an appointment slot.
    if intent == "emergency":
        return build_chat_response(
            db=db, hospital_id=request_data.hospital_id,
            session_id=session_id, message=request_data.message,
            answer=get_medical_safety_answer(emergency=True),
            intent="emergency", sources=[],
        )
    if intent == "medical_safety":
        return build_chat_response(
            db=db, hospital_id=request_data.hospital_id,
            session_id=session_id, message=request_data.message,
            answer=get_medical_safety_answer(emergency=False),
            intent="medical_safety", sources=[],
        )

    current_state = get_conversation_state(
        db=db,
        hospital_id=request_data.hospital_id,
        session_id=session_id
    )

    active_booking_draft = get_active_appointment_draft(
        db=db,
        hospital_id=request_data.hospital_id,
        session_id=session_id,
    )

    # The LLM can distinguish stopping an unfinished chat task from cancelling
    # an actual appointment. Clear temporary session state only; do not touch
    # the appointments or patient records, and do not rely on keyword matching.
    if intent == "stop_workflow":
        stopped = bool(current_state or active_booking_draft)
        if current_state:
            clear_conversation_state(db, request_data.hospital_id, session_id)
        _discard_unfinished_draft(db, active_booking_draft)
        directive = (
            "The patient's unfinished chat task has been stopped. No booked "
            "appointment or patient record was changed. Naturally acknowledge "
            "this and invite a new question. Do not imply that an existing "
            "appointment was cancelled."
            if stopped else
            "There was no unfinished task to stop. Explain this naturally; "
            "do not imply any existing appointment was changed."
        )
        return build_chat_response(
            db=db, hospital_id=request_data.hospital_id,
            session_id=session_id, message=request_data.message,
            answer=directive, intent="stop_workflow", sources=[],
            safe_fallback_answer=(
                "I stopped the unfinished task. Existing appointments were not changed."
                if stopped else "There is no unfinished task to stop."
            ),
        )

    # A clear switch to a different sensitive task takes priority over an old
    # workflow's pending question. Ordinary side questions preserve state.
    new_mode = _task_mode(intent)
    old_mode = str((current_state or {}).get("mode") or "").strip().lower()
    if new_mode and not bool(ai_understanding.get("is_side_question")):
        continuing_retention = old_mode == "cancel_retention" and intent in {
            "cancel_appointment", "reschedule_appointment",
        }
        if current_state and old_mode != new_mode and not continuing_retention:
            clear_conversation_state(db, request_data.hospital_id, session_id)
            current_state = None
        # From cancel_retention to reschedule, keep the retention metadata; the
        # existing retention handler already knows how to transition safely.
        if active_booking_draft:
            _discard_unfinished_draft(db, active_booking_draft)
            active_booking_draft = None

    # EXPLICIT NEW BOOKING OVERRIDES AN OLD NON-BOOKING WORKFLOW.
    # A patient may change their mind and request a separate/new appointment
    # while a previous status/cancel/reschedule/correction state still exists.
    # Backend state must not force that new request back into rescheduling.
    if (
        intent == "book_appointment"
        and current_state
        and str(current_state.get("mode") or "").strip().lower()
        in {"reschedule", "cancel", "cancel_retention", "status", "patient_correction"}
        and not bool(ai_understanding.get("is_side_question"))
    ):
        clear_conversation_state(
            db,
            request_data.hospital_id,
            session_id,
        )

        # If a stale collecting draft also survived from an older flow, close it
        # so "new appointment" starts from a clean booking draft.
        if active_booking_draft:
            active_booking_draft.status = "cancelled"
            active_booking_draft.updated_at = datetime.utcnow()
            db.commit()
            active_booking_draft = None

        return handle_appointment_booking_flow(
            db=db,
            request_data=request_data,
            hospital=hospital,
            session_id=session_id,
            chat_history=chat_history,
            ai_understanding=ai_understanding,
        )

    # A temporary informational interruption must not destroy an active booking,
    # status, cancel, reschedule or correction workflow. The model identifies the
    # interruption semantically; backend facts remain grounded and state is kept.
    # Social interjections are conversational interruptions, not booking data.
    # Preserve any active workflow, even if the model did not explicitly set
    # is_side_question for a greeting/thanks/general conversation turn.
    is_read_only_interruption = intent in {
        "greeting", "thanks", "general_question", "general_health_info",
        "doctor_information", "hospital_information", "doctor_availability",
    }
    if (current_state or active_booking_draft) and is_read_only_interruption:
        side_response = handle_active_workflow_side_question(
            db=db,
            request_data=request_data,
            hospital=hospital,
            session_id=session_id,
            chat_history=chat_history,
            ai_understanding=ai_understanding,
        )
        if side_response is not None:
            return side_response

    # Backend state machine has priority over normal routing.
    # A cancellation gets one professional retention attempt. The next turn is
    # interpreted semantically by the LLM as reschedule vs proceed-cancel.
    if current_state and current_state.get("mode") == "cancel_retention":
        return handle_cancel_retention_state(
            db=db,
            request_data=request_data,
            hospital=hospital,
            session_id=session_id,
            chat_history=chat_history,
            ai_understanding=ai_understanding,
            current_state=current_state,
        )

    # Once the patient has chosen to continue cancellation, keep every
    # short follow-up (ID, phone, correction) inside the same cancellation
    # workflow instead of reclassifying it as a brand-new cancellation request.
    if current_state and current_state.get("mode") == "cancel":
        return handle_ai_cancel_flow(
            db=db,
            request_data=request_data,
            session_id=session_id,
            chat_history=chat_history,
            ai_understanding=ai_understanding,
            current_state=current_state,
        )

    # Keep short follow-ups (ID / phone) inside an active appointment-status
    # workflow so the patient is not forced to repeat information.
    if current_state and current_state.get("mode") == "status":
        return handle_ai_status_flow(
            db=db,
            request_data=request_data,
            session_id=session_id,
            chat_history=chat_history,
            ai_understanding=ai_understanding,
            current_state=current_state,
        )

    # If a reschedule workflow is active, every follow-up is interpreted inside that workflow
    # until the backend completes it or asks for missing details.
    if current_state and current_state.get("mode") == "reschedule":
        # A direct read-only availability question with no appointment/reschedule context can still be shown separately.
        # Otherwise, continue the active reschedule workflow.
        if intent in ["doctor_availability"] and not current_state.get("appointment_id") and not current_state.get("patient_phone"):
            return handle_ai_availability_only_flow(
                db=db,
                request_data=request_data,
                hospital=hospital,
                session_id=session_id,
                chat_history=chat_history,
                ai_understanding=ai_understanding
            )

        return handle_ai_reschedule_state_flow(
            db=db,
            request_data=request_data,
            hospital=hospital,
            session_id=session_id,
            chat_history=chat_history,
            ai_understanding=ai_understanding,
            current_state=current_state
        )

    # Read-only availability must stay separate from booking/reschedule drafts.
    if is_direct_availability_message(message, ai_understanding):
        return handle_ai_availability_only_flow(
            db=db,
            request_data=request_data,
            hospital=hospital,
            session_id=session_id,
            chat_history=chat_history,
            ai_understanding=ai_understanding
        )

    if intent == "emergency":
        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=get_medical_safety_answer(emergency=True),
            intent="emergency",
            sources=[]
        )

    if should_block_medical_request(message, intent):
        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=get_medical_safety_answer(emergency=False),
            intent="medical_safety",
            sources=[]
        )

    if intent == "general_health_info":
        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=get_general_health_information_answer(request_data.message, chat_history),
            intent="general_health_info",
            sources=[]
        )

    # Continue an active patient-correction workflow even if a short follow-up
    # such as YES/NO is classified by the LLM as unknown.
    if current_state and current_state.get("mode") == "patient_correction":
        return handle_ai_patient_correction(
            db=db,
            request_data=request_data,
            session_id=session_id,
            chat_history=chat_history,
            ai_understanding=ai_understanding,
            current_state=current_state,
        )

    # BOOKING ROUTING GUARD:
    # Once a new-appointment draft exists, normal follow-up values (name/phone/date/time)
    # belong to that draft. A bare phone number must never be redirected to the existing-
    # patient correction workflow merely because the LLM guessed `correct_patient_info`.
    # active_booking_draft was loaded before workflow routing so interruptions
    # can be handled consistently for every active flow.

    # Backwards-compatible booking-specific side-question guard. Normally the
    # generic interruption handler above has already returned.
    # A patient may ask a temporary question in the middle of booking (for
    # example about the selected doctor's fee). The LLM brain identifies this
    # semantically. Answer it without discarding/restarting the booking draft.
    if active_booking_draft and bool(ai_understanding.get("is_side_question")):
        if intent in {"doctor_information", "hospital_information"}:
            side_answer, side_sources = build_verified_hospital_answer(
                db=db,
                hospital_id=request_data.hospital_id,
                message=message,
                intent=intent,
                ai_understanding=ai_understanding,
            )

            if not side_answer:
                side_answer, side_sources = rag_service.build_grounded_document_answer(
                    db=db,
                    hospital_id=request_data.hospital_id,
                    question=message,
                    max_results=2,
                )

            if not side_answer:
                side_answer = build_unconfirmed_hospital_answer(
                    db=db,
                    hospital_id=request_data.hospital_id,
                )
                side_sources = []

            return build_chat_response(
                db=db,
                hospital_id=request_data.hospital_id,
                session_id=session_id,
                message=request_data.message,
                answer=side_answer,
                intent=intent,
                sources=side_sources,
                resume_active_workflow=True,
            )

        if intent == "general_question":
            return build_chat_response(
                db=db,
                hospital_id=request_data.hospital_id,
                session_id=session_id,
                message=request_data.message,
                answer=(
                    "I can help with general information. For anything specific to this hospital, I will only use confirmed hospital data."
                ),
                intent="general_question",
                sources=[],
                resume_active_workflow=True,
            )

    if active_booking_draft:
        explicit_existing_correction = (
            intent == "correct_patient_info"
            and bool(ai_understanding.get("existing_record_correction"))
        )

        explicit_other_workflow = intent in {
            "reschedule_appointment",
            "cancel_appointment",
            "appointment_status",
            "human_support",
        }

        if not explicit_existing_correction and not explicit_other_workflow:
            return handle_appointment_booking_flow(
                db=db,
                request_data=request_data,
                hospital=hospital,
                session_id=session_id,
                chat_history=chat_history,
                ai_understanding=ai_understanding
            )

    if intent == "correct_patient_info":
        return handle_ai_patient_correction(
            db=db,
            request_data=request_data,
            session_id=session_id,
            chat_history=chat_history,
            ai_understanding=ai_understanding
        )

    if intent == "reschedule_appointment":
        # Start a real backend state. Do not cancel it on follow-up.
        return handle_ai_reschedule_state_flow(
            db=db,
            request_data=request_data,
            hospital=hospital,
            session_id=session_id,
            chat_history=chat_history,
            ai_understanding=ai_understanding,
            current_state=None
        )

    if intent == "cancel_appointment":
        clear_conversation_state(db, request_data.hospital_id, session_id)
        return start_cancel_retention_flow(
            db=db,
            request_data=request_data,
            session_id=session_id,
            chat_history=chat_history,
            ai_understanding=ai_understanding,
        )

    if intent == "appointment_status":
        clear_conversation_state(db, request_data.hospital_id, session_id)
        return handle_ai_status_flow(
            db=db,
            request_data=request_data,
            session_id=session_id,
            chat_history=chat_history,
            ai_understanding=ai_understanding,
            current_state=None,
        )

    if intent == "book_appointment":
        clear_conversation_state(db, request_data.hospital_id, session_id)
        return handle_appointment_booking_flow(
            db=db,
            request_data=request_data,
            hospital=hospital,
            session_id=session_id,
            chat_history=chat_history,
            ai_understanding=ai_understanding
        )

    if intent == "human_support":
        clear_conversation_state(db, request_data.hospital_id, session_id)
        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer="Reception/support se baat karne ke liye apna name, phone number aur question bhej dein.",
            intent="human_support",
            sources=[]
        )

    # SECURITY / HALLUCINATION GUARD:
    # Unknown intent must never reach a generative factual-answer path. However, a
    # strong deterministic DB or document match is safe to return even if the AI
    # classifier was uncertain. If no verified evidence exists, ask for clarity.
    if intent == "unknown":
        unknown_verified_answer, unknown_verified_sources = build_verified_hospital_answer(
            db=db,
            hospital_id=request_data.hospital_id,
            message=message,
            intent=intent,
            ai_understanding=ai_understanding,
        )

        if unknown_verified_answer:
            return build_chat_response(
                db=db,
                hospital_id=request_data.hospital_id,
                session_id=session_id,
                message=request_data.message,
                answer=unknown_verified_answer,
                intent="verified_information",
                sources=unknown_verified_sources
            )

        unknown_document_answer, unknown_document_sources = rag_service.build_grounded_document_answer(
            db=db,
            hospital_id=request_data.hospital_id,
            question=message,
            max_results=2
        )

        if unknown_document_answer:
            return build_chat_response(
                db=db,
                hospital_id=request_data.hospital_id,
                session_id=session_id,
                message=request_data.message,
                answer=unknown_document_answer,
                intent="document_grounded_information",
                sources=unknown_document_sources
            )

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=(
                "I’m not fully sure what you mean. Please rephrase your question a little more clearly. "
                "I can help with doctors and availability, appointments, hospital services, lab tests, "
                "fees, timings, and hospital contact information."
            ),
            intent="clarification_needed",
            sources=[]
        )

    # STRICT GROUNDING GUARD:
    # Factual hospital answers are now constructed only from verified database/FAQ
    # evidence. The LLM is not allowed to rewrite or supplement these facts.
    # Therefore: no matching evidence -> no factual answer.
    if intent in ["greeting", "thanks"]:
        greeting_answer = (
            "Acknowledge the patient's thanks naturally and warmly, then offer help if appropriate."
            if intent == "thanks"
            else "Respond naturally to the patient's greeting or casual check-in, then briefly offer hospital help if appropriate. Do not list every feature unless the patient asks."
        )

        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=greeting_answer,
            intent=intent,
            sources=[]
        )

    # General conversation is answered by the LLM brain. Hospital-specific
    # questions are classified separately and remain grounded in DB/RAG data.
    if intent == "general_question":
        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=(
                "Answer the patient's general conversational question naturally. If the question becomes specific to this hospital, use only confirmed hospital data."
            ),
            intent="general_question",
            sources=[],
        )

    verified_answer, verified_sources = build_verified_hospital_answer(
        db=db,
        hospital_id=request_data.hospital_id,
        message=message,
        intent=intent,
        ai_understanding=ai_understanding,
    )

    if verified_answer:
        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=verified_answer,
            intent=intent,
            sources=verified_sources
        )

    # DOCUMENT GROUNDING FALLBACK:
    # Structured DB/FAQ evidence remains the first source of truth. If it does not
    # contain the requested fact, search uploaded hospital documents. This path is
    # deterministic: rag_service returns only matched document sentences and does
    # not ask an LLM to invent or complete missing information.
    document_answer, document_sources = rag_service.build_grounded_document_answer(
        db=db,
        hospital_id=request_data.hospital_id,
        question=message,
        max_results=2
    )

    if document_answer:
        return build_chat_response(
            db=db,
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            message=request_data.message,
            answer=document_answer,
            intent="document_grounded_information",
            sources=document_sources
        )

    return build_chat_response(
        db=db,
        hospital_id=request_data.hospital_id,
        session_id=session_id,
        message=request_data.message,
        answer=build_unconfirmed_hospital_answer(
            db=db,
            hospital_id=request_data.hospital_id
        ),
        intent="information_unconfirmed",
        sources=[]
    )


def handle_chat_message(db: Session, request_data: ChatMessageRequest):
    """Top-level chat safety boundary.

    Expected workflow/business errors are normally handled inside their dedicated
    state machines. This wrapper catches anything that escapes, rolls back the
    transaction, converts it to a patient-safe structured error, and prevents
    technical exception text from leaking through the API.
    """
    try:
        return _handle_chat_message_impl(db=db, request_data=request_data)
    except Exception as error:
        try:
            db.rollback()
        except Exception:
            pass

        info = error_service.classify_exception(error)
        session_id = normalize_session_id(getattr(request_data, "session_id", "default"))
        hospital_id = getattr(request_data, "hospital_id", None)
        message = str(getattr(request_data, "message", "") or "")

        if hospital_id:
            try:
                return build_chat_response(
                    db=db,
                    hospital_id=hospital_id,
                    session_id=session_id,
                    message=message,
                    answer=error_service.build_llm_directive(info),
                    intent="action_error",
                    sources=[],
                    safe_fallback_answer=info.patient_message,
                )
            except Exception:
                try:
                    db.rollback()
                except Exception:
                    pass

        return {
            "message": message,
            "answer": info.patient_message,
            "intent": "action_error",
            "sources": [],
            "session_id": session_id,
        }

