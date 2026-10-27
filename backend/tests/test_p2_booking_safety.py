from datetime import date, time, timedelta

from app.models.appointment import Appointment
from app.models.doctor import Doctor
from app.models.hospital import Hospital
from app.models.schedule import Schedule
from app.schemas.public_booking import PublicBookAppointmentRequest
from app.services import public_booking_service


def _next_weekday(day_index: int) -> date:
    today = date.today()
    delta = (day_index - today.weekday()) % 7
    if delta == 0:
        delta = 7
    return today + timedelta(days=delta)


def _seed_doctor(db_session):
    hospital = Hospital(name="Booking Test Hospital")
    db_session.add(hospital)
    db_session.commit()
    db_session.refresh(hospital)

    doctor = Doctor(
        hospital_id=hospital.id,
        name="Dr Test",
        specialization="Medicine",
        consultation_fee=1000,
        is_active=True,
    )
    db_session.add(doctor)
    db_session.commit()
    db_session.refresh(doctor)

    target_date = _next_weekday(0)  # Monday
    schedule = Schedule(
        hospital_id=hospital.id,
        doctor_id=doctor.id,
        day_of_week="Monday",
        start_time=time(17, 0),
        end_time=time(19, 0),
        slot_duration_minutes=30,
        is_active=True,
    )
    db_session.add(schedule)
    db_session.commit()
    return hospital, doctor, target_date


def test_booked_slot_is_removed_from_availability(db_session):
    hospital, doctor, target_date = _seed_doctor(db_session)

    request = PublicBookAppointmentRequest(
        hospital_id=hospital.id,
        doctor_id=doctor.id,
        patient_name="Patient One",
        patient_phone="03000000001",
        appointment_date=target_date,
        appointment_time=time(17, 30),
    )
    public_booking_service.book_public_appointment(db_session, request)

    slots = public_booking_service.get_available_slots(
        db_session, hospital.id, doctor.id, target_date
    )["available_slots"]

    assert "17:30:00" not in slots
    assert "17:00:00" in slots
    assert "18:00:00" in slots


def test_exact_booking_retry_is_idempotent(db_session):
    hospital, doctor, target_date = _seed_doctor(db_session)

    request = PublicBookAppointmentRequest(
        hospital_id=hospital.id,
        doctor_id=doctor.id,
        patient_name="Patient Retry",
        patient_phone="03000000002",
        appointment_date=target_date,
        appointment_time=time(18, 0),
    )

    first = public_booking_service.book_public_appointment(db_session, request)
    second = public_booking_service.book_public_appointment(db_session, request)

    assert second["appointment_id"] == first["appointment_id"]
    assert second["idempotent_replay"] is True
    assert db_session.query(Appointment).count() == 1
