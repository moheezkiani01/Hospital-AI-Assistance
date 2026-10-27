"""Hospital AI Assistant: safe offline chat/booking integration checks.

Place in backend/scripts/ and run from backend/:
    python scripts/check_chat_integration.py

All tests use disposable SQLite databases and mocked AI interpretations.
No real provider requests, patient records, or OTP calls are made.
When FastAPI authentication dependencies are installed, an additional check
runs the real public chat HTTP route with a temporary database.
"""
from __future__ import annotations

import sys
import tempfile
from contextlib import ExitStack
from datetime import date, time, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db.base import Base  # noqa: E402; registers project models
from app.models.appointment import Appointment  # noqa: E402
from app.models.appointment_draft import AppointmentDraft  # noqa: E402
from app.models.doctor import Doctor  # noqa: E402
from app.models.hospital import Hospital  # noqa: E402
from app.models.schedule import Schedule  # noqa: E402
from app.schemas.chat import ChatMessageRequest  # noqa: E402
from app.services import brain_service, chat_service  # noqa: E402


def next_monday() -> date:
    today = date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)


class IsolatedClinic:
    """A fresh disposable database; never imports app.main or uses DATABASE_URL."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hospital-chat-test-")
        self.engine = create_engine(
            "sqlite:///" + str(Path(self.tmp.name) / "synthetic.sqlite3"),
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, autoflush=False)
        with self.session_factory() as db:
            hospital = Hospital(name="Synthetic Clinic For Testing")
            db.add(hospital)
            db.flush()
            doctor = Doctor(
                hospital_id=hospital.id, name="Dr Example",
                specialization="General", consultation_fee=500, is_active=True,
            )
            db.add(doctor)
            db.flush()
            db.add(Schedule(
                hospital_id=hospital.id, doctor_id=doctor.id,
                day_of_week="Monday", start_time=time(9), end_time=time(12),
                slot_duration_minutes=30, is_active=True,
            ))
            db.commit()
            self.hospital_id = hospital.id
            self.doctor_id = doctor.id
        self.day = next_monday()
        return self

    def __exit__(self, *_):
        self.engine.dispose()
        self.tmp.cleanup()

    def ask(self, message: str, session: str = "synthetic-a") -> dict:
        with self.session_factory() as db:
            return chat_service.handle_chat_message(
                db, ChatMessageRequest(
                    hospital_id=self.hospital_id,
                    session_id=session,
                    source="website",
                    message=message,
                ),
            )

    def count(self, model) -> int:
        with self.session_factory() as db:
            return db.query(model).count()


def fake_ai_decisions(decisions: dict, *, fail_reply=False):
    """Patch only AI outputs; all workflow/database logic remains real."""
    def understand(**kwargs):
        incoming = kwargs["request_data"].message
        return {
            "_brain_available": True, "language_style": "english",
            "confidence": 1.0, **dict(decisions[incoming]),
        }

    stack = ExitStack()
    stack.enter_context(patch.object(chat_service, "get_ai_message_understanding", understand))
    stack.enter_context(patch.object(
        chat_service, "make_ai_reply",
        lambda **kwargs: kwargs.get("base_instruction", ""),
    ))
    stack.enter_context(patch.object(
        brain_service, "compose_patient_reply",
        (lambda **kwargs: None) if fail_reply
        else (lambda **kwargs: kwargs.get("authoritative_result")),
    ))
    return stack


def check_greeting() -> None:
    with IsolatedClinic() as clinic, fake_ai_decisions({"Hi": {"intent": "greeting"}}):
        response = clinic.ask("Hi")
        assert response["intent"] == "greeting", response
        assert clinic.count(Appointment) == 0
        assert clinic.count(AppointmentDraft) == 0


def check_multiturn_booking() -> None:
    with IsolatedClinic() as clinic:
        turns = {
            "Book": {"intent": "book_appointment"},
            "Dr Example": {"intent": "book_appointment", "doctor_id": clinic.doctor_id},
            "Monday": {"intent": "book_appointment", "appointment_date": clinic.day.isoformat()},
            "09:00": {"intent": "book_appointment", "appointment_time": "09:00", "time_was_mentioned": True},
            "Name: Demo Patient": {"intent": "book_appointment", "patient_name": "Demo Patient"},
            "03000000001": {"intent": "book_appointment", "patient_phone": "03000000001"},
        }
        with fake_ai_decisions(turns):
            for message in list(turns)[:-1]:
                response = clinic.ask(message)
                assert response["intent"] != "appointment_confirmed", response
            confirmed = clinic.ask("03000000001")
            assert confirmed["intent"] == "appointment_confirmed", confirmed
            assert clinic.count(Appointment) == 1
            assert clinic.count(AppointmentDraft) == 1  # completed draft may be retained
            with clinic.session_factory() as db:
                entry = db.query(Appointment).one()
                assert entry.doctor_id == clinic.doctor_id
                assert entry.appointment_date == clinic.day
                assert entry.appointment_time == time(9)


def check_slot_conflict() -> None:
    with IsolatedClinic() as clinic:
        turns = {
            "First": {"intent": "book_appointment", "doctor_id": clinic.doctor_id,
                      "appointment_date": clinic.day.isoformat(), "appointment_time": "09:00",
                      "patient_name": "Demo First", "patient_phone": "03000000001"},
            "Second": {"intent": "book_appointment", "doctor_id": clinic.doctor_id,
                       "appointment_date": clinic.day.isoformat(), "appointment_time": "09:00",
                       "patient_name": "Demo Second", "patient_phone": "03000000002"},
        }
        with fake_ai_decisions(turns):
            first = clinic.ask("First", session="synthetic-first")
            second = clinic.ask("Second", session="synthetic-second")
            assert first["intent"] == "appointment_confirmed", first
            assert second["intent"] in {"appointment_slot_not_available", "appointment_no_slots"}, second
            assert clinic.count(Appointment) == 1


def check_interruption_and_isolation() -> None:
    with IsolatedClinic() as clinic:
        turns = {
            "Start": {"intent": "book_appointment", "doctor_id": clinic.doctor_id},
            "Thanks": {"intent": "thanks"},
            "Continue": {"intent": "book_appointment", "appointment_date": clinic.day.isoformat()},
            "Hi again": {"intent": "greeting"},
        }
        with fake_ai_decisions(turns):
            clinic.ask("Start", session="synthetic-a")
            response = clinic.ask("Thanks", session="synthetic-a")
            assert response["intent"] == "thanks", response
            clinic.ask("Hi again", session="synthetic-b")
            with clinic.session_factory() as db:
                a = chat_service.get_active_appointment_draft(db, clinic.hospital_id, "synthetic-a")
                b = chat_service.get_active_appointment_draft(db, clinic.hospital_id, "synthetic-b")
                assert a is not None and a.doctor_id == clinic.doctor_id
                assert b is None, "Booking context leaked into another session"
            clinic.ask("Continue", session="synthetic-a")
            with clinic.session_factory() as db:
                a = chat_service.get_active_appointment_draft(db, clinic.hospital_id, "synthetic-a")
                assert a is not None and a.appointment_date == clinic.day
            assert clinic.count(Appointment) == 0


def check_ai_reply_failure() -> None:
    with IsolatedClinic() as clinic:
        turns = {"Book despite reply failure": {
            "intent": "book_appointment", "doctor_id": clinic.doctor_id,
            "appointment_date": clinic.day.isoformat(), "appointment_time": "09:30",
            "patient_name": "Demo Patient", "patient_phone": "03000000001",
        }}
        with fake_ai_decisions(turns, fail_reply=True):
            answer = clinic.ask("Book despite reply failure")
            assert answer["intent"] == "appointment_confirmed", answer
            assert "Appointment ID" in answer["answer"], answer
            assert clinic.count(Appointment) == 1


def check_public_api_route() -> None:
    """Optional local HTTP route test; requires the project's auth dependencies."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.rate_limit_deps import chat_rate_limit
    from app.api.v1.endpoints import chat as chat_endpoint
    from app.db.database import get_db

    with IsolatedClinic() as clinic:
        def test_db():
            with clinic.session_factory() as db:
                yield db

        app = FastAPI()
        app.include_router(chat_endpoint.router, prefix="/api/v1/chat")
        app.dependency_overrides[get_db] = test_db
        app.dependency_overrides[chat_rate_limit] = lambda: None
        with fake_ai_decisions({"Hi": {"intent": "greeting"}}):
            with TestClient(app) as client:
                response = client.post("/api/v1/chat/message", json={
                    "hospital_id": clinic.hospital_id, "session_id": "synthetic-http", "message": "Hi",
                })
                assert response.status_code == 200, response.text[:200]
                assert response.json()["intent"] == "greeting", response.json()
                denied = client.post("/api/v1/chat/message", json={
                    "hospital_id": clinic.hospital_id, "session_id": "synthetic-http",
                    "message": "Hi", "source": "whatsapp", "whatsapp_number": "+923000000001",
                })
                assert denied.status_code == 400, denied.status_code
        assert clinic.count(Appointment) == 0


def main() -> int:
    checks = [
        ("Greeting does not start booking", check_greeting),
        ("Multi-turn booking writes one valid appointment", check_multiturn_booking),
        ("Competing patients cannot take an occupied slot", check_slot_conflict),
        ("Side questions preserve drafts and isolate sessions", check_interruption_and_isolation),
        ("Committed booking survives response-model failure", check_ai_reply_failure),
    ]
    failed = 0
    passed = 0
    skipped = 0
    for name, func in checks:
        try:
            func()
            passed += 1
            print("PASS ", name)
        except Exception as exc:
            failed += 1
            print("FAIL ", name, "(", type(exc).__name__, ")")
    try:
        check_public_api_route()
        passed += 1
        print("PASS  Actual FastAPI public chat route and identity boundary")
    except (ImportError, ModuleNotFoundError) as exc:
        skipped += 1
        print("SKIP  FastAPI route test: missing local dependency:", exc.name)
    except Exception as exc:
        failed += 1
        print("FAIL  FastAPI route test (", type(exc).__name__, ")")
    print(f"\nResults: passed={passed}, skipped={skipped}, failed={failed}")
    print("All checks used isolated SQLite data and simulated AI outputs.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
