"""Public cancel/reschedule/status: wrong phone numbers lock the appointment for a while."""
from datetime import date, time, timedelta

import pytest

from app.core.rate_limit import verification_failures
from app.models.doctor import Doctor
from app.models.hospital import Hospital
from app.models.schedule import Schedule
from app.schemas.public_booking import PublicBookAppointmentRequest
from app.services import public_booking_service


@pytest.fixture(autouse=True)
def _clean_lockouts():
    verification_failures.reset()
    yield
    verification_failures.reset()


def _next_monday() -> date:
    today = date.today()
    delta = (0 - today.weekday()) % 7
    return today + timedelta(days=delta or 7)


def _book_one(db_session):
    hospital = Hospital(name="Lockout Test Hospital")
    db_session.add(hospital)
    db_session.commit()
    db_session.refresh(hospital)

    doctor = Doctor(
        hospital_id=hospital.id, name="Dr Test", specialization="Medicine",
        consultation_fee=1000, is_active=True,
    )
    db_session.add(doctor)
    db_session.commit()
    db_session.refresh(doctor)

    db_session.add(
        Schedule(
            hospital_id=hospital.id, doctor_id=doctor.id, day_of_week="Monday",
            start_time=time(17, 0), end_time=time(19, 0),
            slot_duration_minutes=30, is_active=True,
        )
    )
    db_session.commit()

    booked = public_booking_service.book_public_appointment(
        db_session,
        PublicBookAppointmentRequest(
            hospital_id=hospital.id, doctor_id=doctor.id,
            patient_name="Patient One", patient_phone="03000000001",
            appointment_date=_next_monday(), appointment_time=time(17, 30),
        ),
    )
    return hospital.id, booked["appointment_id"]


def test_correct_phone_is_accepted(db_session):
    hospital_id, appointment_id = _book_one(db_session)

    appointment, patient = public_booking_service.get_verified_public_appointment(
        db_session, hospital_id, appointment_id, "03000000001"
    )
    assert appointment.id == appointment_id
    assert patient.phone == "03000000001"


def test_repeated_wrong_phones_lock_out_even_the_right_one(db_session):
    from app.core.config import settings

    hospital_id, appointment_id = _book_one(db_session)

    for guess in range(settings.VERIFY_MAX_FAILURES):
        with pytest.raises(ValueError, match="does not match"):
            public_booking_service.get_verified_public_appointment(
                db_session, hospital_id, appointment_id, f"0311000{guess:04d}"
            )

    with pytest.raises(ValueError, match="Too many incorrect attempts"):
        public_booking_service.get_verified_public_appointment(
            db_session, hospital_id, appointment_id, "03000000001"
        )


def test_unknown_appointment_ids_do_not_trigger_lockouts(db_session):
    hospital_id, appointment_id = _book_one(db_session)

    for _ in range(10):
        with pytest.raises(ValueError, match="not found"):
            public_booking_service.get_verified_public_appointment(
                db_session, hospital_id, appointment_id + 1000, "03000000001"
            )

    # The real appointment is unaffected.
    public_booking_service.get_verified_public_appointment(
        db_session, hospital_id, appointment_id, "03000000001"
    )
