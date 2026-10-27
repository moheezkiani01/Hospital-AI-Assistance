import re
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from app.models.patient_chat_memory import PatientChatMemory


SAVE_WORDS = [
    "remember this",
    "remember that",
    "save this",
    "save that",
    "save it",
    "note this",
    "keep this",
    "save for future",
    "remember for future",
    "yaad rakh",
    "yaad rakhna",
    "save kar lo",
    "future ke liye save",
    "future ke liye yaad",
]


TEST_WORDS = [
    "test",
    "lab",
    "cbc",
    "blood test",
    "sugar test",
    "xray",
    "x-ray",
    "urine test",
    "report",
    "ٹیسٹ",
    "رپورٹ",
]


APPOINTMENT_WORDS = [
    "appointment",
    "booking",
    "doctor appointment",
    "cancel appointment",
    "reschedule",
    "اپائنٹمنٹ",
]


def normalize_session_id(session_id: Optional[str]) -> str:
    if not session_id:
        return "default"

    clean_session_id = str(session_id).strip()

    if not clean_session_id:
        return "default"

    return clean_session_id[:150]


def detect_language(message: str) -> str:
    message_lower = message.lower()

    urdu_chars = re.findall(r"[\u0600-\u06FF]", message)

    if urdu_chars:
        return "Urdu"

    roman_urdu_words = [
        "kia",
        "kya",
        "mujhe",
        "mjy",
        "mera",
        "meri",
        "batao",
        "samjhao",
        "kaise",
        "kese",
        "hai",
        "hain",
        "nahi",
        "han",
        "acha",
        "theek",
    ]

    for word in roman_urdu_words:
        if word in message_lower:
            return "Roman Urdu"

    return "English"


def clean_text(text: str, max_length: int = 500) -> str:
    text = str(text).strip()
    text = re.sub(r"\s+", " ", text)

    if len(text) > max_length:
        text = text[:max_length].strip() + "..."

    return text


def extract_patient_name(message: str) -> Optional[str]:
    patterns = [
        r"\bmy name is\s+([a-zA-Z][a-zA-Z\s]{1,60})",
        r"\bmy name\s+is\s+([a-zA-Z][a-zA-Z\s]{1,60})",
        r"\bmera naam\s+([a-zA-Z][a-zA-Z\s]{1,60})",
        r"\bmera name\s+([a-zA-Z][a-zA-Z\s]{1,60})",
        r"\bmeri name\s+([a-zA-Z][a-zA-Z\s]{1,60})",
        r"\bnaam hai\s+([a-zA-Z][a-zA-Z\s]{1,60})",
    ]

    message_clean = clean_text(message, 200)

    for pattern in patterns:
        match = re.search(pattern, message_clean, re.IGNORECASE)

        if match:
            name = match.group(1).strip()

            stop_words = [
                "and",
                "aur",
                "hai",
                "hy",
                "he",
                "please",
                "plz",
                "i",
                "mujhe",
                "mera",
                "meri",
            ]

            name_words = []

            for word in name.split():
                if word.lower() in stop_words:
                    break

                name_words.append(word)

            final_name = " ".join(name_words).strip(" .,!?:;")

            if 2 <= len(final_name) <= 80:
                return final_name.title()

    return None


def extract_phone_from_session(session_id: str) -> Optional[str]:
    if session_id.startswith("whatsapp_"):
        return session_id.replace("whatsapp_", "").strip()

    return None


def patient_asked_to_save(message: str) -> bool:
    message_lower = message.lower()

    for word in SAVE_WORDS:
        if word in message_lower:
            return True

    return False


def extract_save_text(message: str) -> str:
    text = clean_text(message, 700)

    remove_phrases = [
        "remember this",
        "remember that",
        "save this",
        "save that",
        "save it",
        "note this",
        "keep this",
        "save for future",
        "remember for future",
        "yaad rakhna",
        "yaad rakh",
        "save kar lo",
        "future ke liye save",
        "future ke liye yaad",
    ]

    lowered = text.lower()

    for phrase in remove_phrases:
        if phrase in lowered:
            index = lowered.find(phrase)
            text = text[:index] + text[index + len(phrase):]
            break

    text = text.strip(" :-,.")

    if not text:
        text = clean_text(message, 700)

    return text


def message_has_any_word(message: str, words: list) -> bool:
    message_lower = message.lower()

    for word in words:
        if word in message_lower:
            return True

    return False


def append_memory(existing_text: Optional[str], new_text: str, max_chars: int = 4000) -> str:
    existing_text = existing_text or ""
    new_text = clean_text(new_text, 700)

    if not new_text:
        return existing_text

    entry = f"- {datetime.utcnow().strftime('%Y-%m-%d')}: {new_text}"

    if entry in existing_text:
        return existing_text

    combined = existing_text.strip()

    if combined:
        combined = combined + "\n" + entry
    else:
        combined = entry

    if len(combined) > max_chars:
        combined = combined[-max_chars:]

    return combined.strip()


def get_or_create_patient_memory(
    db: Session,
    hospital_id: int,
    session_id: str
):
    session_id = normalize_session_id(session_id)

    memory = (
        db.query(PatientChatMemory)
        .filter(
            PatientChatMemory.hospital_id == hospital_id,
            PatientChatMemory.session_id == session_id
        )
        .first()
    )

    if memory:
        return memory

    memory = PatientChatMemory(
        hospital_id=hospital_id,
        session_id=session_id,
        phone_number=extract_phone_from_session(session_id),
        preferred_language=None,
        memory_summary=""
    )

    db.add(memory)
    db.commit()
    db.refresh(memory)

    return memory


def build_memory_summary(memory: PatientChatMemory) -> str:
    lines = []

    if memory.patient_name:
        lines.append(f"Patient name: {memory.patient_name}")

    if memory.preferred_language:
        lines.append(f"Preferred language: {memory.preferred_language}")

    if memory.phone_number:
        lines.append(f"Phone/session: {memory.phone_number}")

    if memory.last_appointment_summary:
        lines.append("Last appointment info:")
        lines.append(memory.last_appointment_summary)

    if memory.last_tests_summary:
        lines.append("Last test/lab info:")
        lines.append(memory.last_tests_summary)

    if memory.saved_information:
        lines.append("Patient asked to remember:")
        lines.append(memory.saved_information)

    if not lines:
        return ""

    return "\n".join(lines).strip()


def update_patient_memory_after_chat(
    db: Session,
    hospital_id: int,
    session_id: str,
    user_message: str,
    assistant_answer: str,
    intent: str
):
    session_id = normalize_session_id(session_id)

    memory = get_or_create_patient_memory(
        db=db,
        hospital_id=hospital_id,
        session_id=session_id
    )

    extracted_name = extract_patient_name(user_message)

    if extracted_name:
        memory.patient_name = extracted_name

    detected_language = detect_language(user_message)

    if detected_language:
        memory.preferred_language = detected_language

    if not memory.phone_number:
        memory.phone_number = extract_phone_from_session(session_id)

    safe_question = clean_text(user_message, 300)
    safe_answer = clean_text(assistant_answer, 300)

    if intent and "appointment" in intent:
        appointment_text = f"Patient asked: {safe_question} | Assistant replied: {safe_answer}"
        memory.last_appointment_summary = append_memory(
            memory.last_appointment_summary,
            appointment_text,
            max_chars=2000
        )

    if message_has_any_word(user_message, APPOINTMENT_WORDS):
        appointment_text = f"Patient mentioned appointment: {safe_question}"
        memory.last_appointment_summary = append_memory(
            memory.last_appointment_summary,
            appointment_text,
            max_chars=2000
        )

    if intent == "lab_test_info" or message_has_any_word(user_message, TEST_WORDS):
        test_text = f"Patient asked: {safe_question} | Assistant replied: {safe_answer}"
        memory.last_tests_summary = append_memory(
            memory.last_tests_summary,
            test_text,
            max_chars=2000
        )

    if patient_asked_to_save(user_message):
        save_text = extract_save_text(user_message)
        memory.saved_information = append_memory(
            memory.saved_information,
            save_text,
            max_chars=4000
        )

    memory.memory_summary = build_memory_summary(memory)
    memory.updated_at = datetime.utcnow()

    db.add(memory)
    db.commit()
    db.refresh(memory)

    return memory


def get_patient_memory_text(
    db: Session,
    hospital_id: int,
    session_id: str
) -> str:
    session_id = normalize_session_id(session_id)

    memory = (
        db.query(PatientChatMemory)
        .filter(
            PatientChatMemory.hospital_id == hospital_id,
            PatientChatMemory.session_id == session_id
        )
        .first()
    )

    if not memory:
        return "No saved patient memory yet."

    memory_text = memory.memory_summary or build_memory_summary(memory)

    if not memory_text:
        return "No saved patient memory yet."

    return memory_text

# Conversation-phase memory: only language style, never medical or identity data.
# This reuses the existing memory table without introducing a migration.
CONVERSATION_LANGUAGES = {
    "english": "english",
    "roman_urdu": "roman_urdu",
    "roman urdu": "roman_urdu",  # Earlier memory versions used a space.
    "urdu": "urdu",
}


def get_conversation_language(db: Session, hospital_id: int, session_id: str) -> Optional[str]:
    """Return the language from this session, not another visitor's history."""
    session_id = normalize_session_id(session_id)
    if session_id == "default":
        return None
    try:
        memory = (
            db.query(PatientChatMemory)
            .filter(
                PatientChatMemory.hospital_id == hospital_id,
                PatientChatMemory.session_id == session_id,
            )
            .first()
        )
    except OperationalError as error:
        # Some older installs haven't run add_patient_chat_memory_table.py.
        # Do not take their entire chatbot offline for an optional preference.
        db.rollback()
        if "patient_chat_memories" not in str(error).lower():
            raise
        return None
    value = str(memory.preferred_language or "").lower() if memory else ""
    return CONVERSATION_LANGUAGES.get(value)


def remember_conversation_language(
    db: Session, hospital_id: int, session_id: str, language_style: str, user_message: str
) -> None:
    """Store only clear LLM-classified language evidence in an isolated session.

    Tiny acknowledgements and numbers should not overwrite the style established
    during a meaningful earlier turn. Do not store the patient's message text.
    """
    session_id = normalize_session_id(session_id)
    style = CONVERSATION_LANGUAGES.get(str(language_style or "").lower())
    if session_id == "default" or not style:
        return
    if len(re.findall(r"[a-zA-Z\u0600-\u06FF]", str(user_message or ""))) < 12:
        return

    try:
        memory = (
            db.query(PatientChatMemory)
            .filter(
                PatientChatMemory.hospital_id == hospital_id,
                PatientChatMemory.session_id == session_id,
            )
            .first()
        )
    except OperationalError as error:
        db.rollback()
        if "patient_chat_memories" not in str(error).lower():
            raise
        return
    if memory is None:
        memory = PatientChatMemory(
            hospital_id=hospital_id,
            session_id=session_id,
            preferred_language=style,
            memory_summary="",
        )
        db.add(memory)
    elif memory.preferred_language == style:
        return
    else:
        memory.preferred_language = style
    memory.updated_at = datetime.utcnow()
    db.commit()
