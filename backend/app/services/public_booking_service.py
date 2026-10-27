import hmac
from datetime import date, datetime, time, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import verification_failures
from app.models.appointment import Appointment
from app.models.doctor import Doctor
from app.models.hospital import Hospital
from app.models.patient import Patient
from app.models.schedule import Schedule
from app.schemas.public_booking import (
    PublicBookAppointmentRequest,
    PublicCancelAppointmentRequest,
    PublicRescheduleAppointmentRequest
)


def ensure_active_slot_unique_index(db: Session):
    """Enforce both active-slot and active-patient/day uniqueness in the DB.

    The second index closes a different race: two requests for the same patient
    and doctor on the same day at different times. Application-level checks
    cannot guarantee uniqueness across concurrent database sessions.
    """
    try:
        if db.bind is None or db.bind.dialect.name not in {"sqlite", "postgresql"}:
            raise RuntimeError(
                "Active appointment database constraints require a migration "
                "for this database engine before bookings can be accepted"
            )
        db.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_active_appointment_slot
                ON appointments (hospital_id, doctor_id, appointment_date, appointment_time)
                WHERE status IN ('booked', 'confirmed')
                """
            )
        )
        db.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_active_patient_doctor_day
                ON appointments (hospital_id, patient_id, doctor_id, appointment_date)
                WHERE status IN ('booked', 'confirmed')
                """
            )
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError(
            "Existing duplicate active appointments must be cleaned before safe booking can continue"
        ) from exc


def _booking_result(appointment: Appointment, doctor: Doctor, *, idempotent_replay: bool = False):
    return {
        "message": "Appointment already booked" if idempotent_replay else "Appointment booked successfully",
        "appointment_id": appointment.id,
        "patient_id": appointment.patient_id,
        "doctor_id": doctor.id,
        "doctor_name": doctor.name,
        "appointment_date": appointment.appointment_date,
        "appointment_time": appointment.appointment_time,
        "status": appointment.status,
        "idempotent_replay": bool(idempotent_replay),
    }


def get_day_name(appointment_date: date) -> str:
    return appointment_date.strftime("%A")


def validate_not_past_date(appointment_date: date):
    today = date.today()

    if appointment_date < today:
        raise ValueError("You cannot book an appointment for a past date")


def is_today(appointment_date: date) -> bool:
    return appointment_date == date.today()


def is_past_time_today(appointment_date: date, appointment_time: time) -> bool:
    if not is_today(appointment_date):
        return False

    selected_datetime = datetime.combine(appointment_date, appointment_time)
    current_datetime = datetime.now()

    return selected_datetime <= current_datetime



def validate_existing_appointment_is_actionable(appointment: Appointment, action: str):
    """
    Only active future appointments may be cancelled or rescheduled.
    This is a backend business rule and must not depend on UI/LLM behavior.
    """
    action_word = "cancelled" if action == "cancel" else "rescheduled"
    status = str(appointment.status or "").strip().lower()

    if status not in {"booked", "confirmed"}:
        if status == "cancelled":
            raise ValueError("This appointment is already cancelled")
        if status in {"completed", "done"}:
            raise ValueError("This appointment is already completed")
        if status in {"no_show", "no-show", "noshow"}:
            raise ValueError("This appointment is already marked as a no-show")
        raise ValueError(f"Only active appointments can be {action_word}")

    if appointment.appointment_date < date.today():
        raise ValueError(f"Past appointments cannot be {action_word}")

    if is_past_time_today(appointment.appointment_date, appointment.appointment_time):
        raise ValueError(f"This appointment time has already passed and cannot be {action_word}")

def generate_time_slots(
    start_time: time,
    end_time: time,
    slot_duration_minutes: int
):
    slots = []

    if slot_duration_minutes <= 0:
        return slots

    today = date.today()

    current_datetime = datetime.combine(today, start_time)
    end_datetime = datetime.combine(today, end_time)

    duration = timedelta(minutes=slot_duration_minutes)
    # A slot is bookable only when the full appointment fits inside the
    # doctor's working hours. Otherwise a 10:00 slot could extend past 10:10.
    while current_datetime + duration <= end_datetime:
        slots.append(current_datetime.time())
        current_datetime += duration

    return slots


def validate_hospital(db: Session, hospital_id: int):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()

    if not hospital:
        raise ValueError("Hospital not found")

    return hospital


def validate_doctor(db: Session, hospital_id: int, doctor_id: int):
    doctor = (
        db.query(Doctor)
        .filter(
            Doctor.id == doctor_id,
            Doctor.hospital_id == hospital_id,
            Doctor.is_active == True
        )
        .first()
    )

    if not doctor:
        raise ValueError("Doctor not found or inactive")

    return doctor


def find_active_patient_doctor_day_appointment(
    db: Session,
    hospital_id: int,
    patient_id: int,
    doctor_id: int,
    appointment_date: date,
    exclude_appointment_id: Optional[int] = None,
):
    """Shared duplicate guard for web, staff and AI-chat appointment workflows.

    A single patient cannot have two active bookings with the same doctor on
    one date, even at different times. Excluding a moved appointment lets it
    reschedule itself without creating a false duplicate.
    """
    query = db.query(Appointment).filter(
        Appointment.hospital_id == hospital_id,
        Appointment.patient_id == patient_id,
        Appointment.doctor_id == doctor_id,
        Appointment.appointment_date == appointment_date,
        Appointment.status.in_(["booked", "confirmed"]),
    )
    if exclude_appointment_id is not None:
        query = query.filter(Appointment.id != exclude_appointment_id)
    return query.first()


def get_public_doctors(db: Session, hospital_id: int):
    validate_hospital(db, hospital_id)

    doctors = (
        db.query(Doctor)
        .join(
            Schedule,
            Schedule.doctor_id == Doctor.id
        )
        .filter(
            Doctor.hospital_id == hospital_id,
            Doctor.is_active == True,
            Schedule.hospital_id == hospital_id,
            Schedule.is_active == True
        )
        .distinct()
        .order_by(Doctor.name.asc())
        .all()
    )

    return doctors


def get_doctor_schedule(
    db: Session,
    hospital_id: int,
    doctor_id: int,
    appointment_date: date
):
    day_name = get_day_name(appointment_date)

    schedules = (
        db.query(Schedule)
        .filter(
            Schedule.hospital_id == hospital_id,
            Schedule.doctor_id == doctor_id,
            Schedule.is_active == True
        )
        .all()
    )

    for schedule in schedules:
        if schedule.day_of_week.lower() == day_name.lower():
            return schedule

    return None


def get_available_slots(
    db: Session,
    hospital_id: int,
    doctor_id: int,
    appointment_date: date,
    exclude_appointment_id: Optional[int] = None
):
    validate_not_past_date(appointment_date)
    validate_hospital(db, hospital_id)
    doctor = validate_doctor(db, hospital_id, doctor_id)

    day_name = get_day_name(appointment_date)

    schedules = (
        db.query(Schedule)
        .filter(
            Schedule.hospital_id == hospital_id,
            Schedule.doctor_id == doctor_id,
            Schedule.day_of_week == day_name,
            Schedule.is_active == True
        )
        .all()
    )

    if not schedules:
        raise ValueError(f"No schedule found for Dr. {doctor.name} on {day_name}")

    booked_query = (
        db.query(Appointment)
        .filter(
            Appointment.hospital_id == hospital_id,
            Appointment.doctor_id == doctor_id,
            Appointment.appointment_date == appointment_date,
            Appointment.status.in_(["booked", "confirmed"])
        )
    )

    if exclude_appointment_id is not None:
        booked_query = booked_query.filter(Appointment.id != exclude_appointment_id)

    booked_appointments = booked_query.all()

    booked_times = set()

    for appointment in booked_appointments:
        if appointment.appointment_time:
            booked_times.add(appointment.appointment_time.strftime("%H:%M:%S"))

    available_slots = []

    # IMPORTANT: availability shown to the patient must use the same time rule
    # as the final booking validation. Otherwise a slot from earlier today can
    # be advertised as available and only be rejected after the patient provides
    # their remaining details. Capture `now` once so every slot in this response
    # is evaluated against one consistent point in time.
    current_datetime = datetime.now()
    is_same_day = appointment_date == current_datetime.date()

    for schedule in schedules:
        schedule_slots = generate_time_slots(
            start_time=schedule.start_time,
            end_time=schedule.end_time,
            slot_duration_minutes=schedule.slot_duration_minutes
        )

        for slot in schedule_slots:
            slot_text = slot.strftime("%H:%M:%S")

            # Never advertise a same-day slot whose start time has already
            # passed. The final booking service already rejects these times;
            # filtering here keeps availability and booking behavior consistent.
            if is_same_day and datetime.combine(appointment_date, slot) <= current_datetime:
                continue

            if slot_text not in booked_times and slot_text not in available_slots:
                available_slots.append(slot_text)

    available_slots = sorted(available_slots)

    return {
        "hospital_id": hospital_id,
        "doctor_id": doctor_id,
        "doctor_name": doctor.name,
        "appointment_date": appointment_date,
        "available_slots": available_slots
    }

def get_or_create_patient(
    db: Session,
    hospital_id: int,
    patient_name: str,
    patient_phone: str,
    patient_email: Optional[str] = None
):
    patient_name = patient_name.strip()
    patient_phone = patient_phone.strip()

    if not patient_name:
        raise ValueError("Patient name is required")

    if not patient_phone:
        raise ValueError("Patient phone number is required")

    patient = (
        db.query(Patient)
        .filter(
            Patient.hospital_id == hospital_id,
            Patient.phone == patient_phone
        )
        .first()
    )

    if patient:
        return patient

    new_patient = Patient(
        hospital_id=hospital_id,
        name=patient_name,
        phone=patient_phone,
        email=patient_email
    )

    db.add(new_patient)
    db.commit()
    db.refresh(new_patient)

    return new_patient


def get_verified_public_appointment(
    db: Session,
    hospital_id: int,
    appointment_id: int,
    patient_phone: str
):
    validate_hospital(db, hospital_id)

    patient_phone = patient_phone.strip()

    if not patient_phone:
        raise ValueError("Patient phone number is required")

    # Brute-force protection: after too many wrong phone numbers for the same
    # appointment, refuse further attempts for a while.
    lock_key = f"public:{hospital_id}:{appointment_id}"
    if verification_failures.locked_for(lock_key):
        raise ValueError(
            "Too many incorrect attempts for this appointment. "
            "Please try again later or contact reception."
        )

    appointment = (
        db.query(Appointment)
        .filter(
            Appointment.id == appointment_id,
            Appointment.hospital_id == hospital_id
        )
        .first()
    )

    if not appointment:
        raise ValueError("Appointment not found")

    patient = (
        db.query(Patient)
        .filter(
            Patient.id == appointment.patient_id,
            Patient.hospital_id == hospital_id
        )
        .first()
    )

    if not patient:
        raise ValueError("Patient record not found")

    if not hmac.compare_digest(
        patient.phone.strip().encode("utf-8"),
        patient_phone.encode("utf-8"),
    ):
        lockout_seconds = int(settings.VERIFY_LOCKOUT_MINUTES) * 60
        verification_failures.register_failure(
            lock_key,
            max_failures=int(settings.VERIFY_MAX_FAILURES),
            window_seconds=lockout_seconds,
            lockout_seconds=lockout_seconds,
        )
        raise ValueError("Phone number does not match this appointment")

    verification_failures.register_success(lock_key)

    return appointment, patient


def book_public_appointment(
    db: Session,
    request_data: PublicBookAppointmentRequest
):
    validate_not_past_date(request_data.appointment_date)

    if is_past_time_today(
        appointment_date=request_data.appointment_date,
        appointment_time=request_data.appointment_time
    ):
        raise ValueError("You cannot book an appointment for a past time")

    validate_hospital(db, request_data.hospital_id)
    doctor = validate_doctor(db, request_data.hospital_id, request_data.doctor_id)

    # Create/resolve the patient BEFORE slot validation so an exact replay can be
    # recognized even though the patient's own booked slot is no longer listed as
    # available. This is critical when a DB commit succeeded but the response LLM
    # failed and the browser/patient retries the same request.
    patient = get_or_create_patient(
        db=db,
        hospital_id=request_data.hospital_id,
        patient_name=request_data.patient_name,
        patient_phone=request_data.patient_phone,
        patient_email=request_data.patient_email
    )

    exact_existing = (
        db.query(Appointment)
        .filter(
            Appointment.hospital_id == request_data.hospital_id,
            Appointment.doctor_id == request_data.doctor_id,
            Appointment.patient_id == patient.id,
            Appointment.appointment_date == request_data.appointment_date,
            Appointment.appointment_time == request_data.appointment_time,
            Appointment.status.in_(["booked", "confirmed"]),
        )
        .order_by(Appointment.id.desc())
        .first()
    )

    if exact_existing:
        return _booking_result(exact_existing, doctor, idempotent_replay=True)

    # Preserve the current business rule: one active appointment with the same
    # doctor on the same date for a patient. Exact same-slot retries were handled
    # above and are success, not an error.
    same_day_existing = find_active_patient_doctor_day_appointment(
        db=db,
        hospital_id=request_data.hospital_id,
        patient_id=patient.id,
        doctor_id=request_data.doctor_id,
        appointment_date=request_data.appointment_date,
    )

    if same_day_existing:
        raise ValueError("You already have an appointment with this doctor on this date")

    slots_data = get_available_slots(
        db=db,
        hospital_id=request_data.hospital_id,
        doctor_id=request_data.doctor_id,
        appointment_date=request_data.appointment_date
    )

    selected_time = request_data.appointment_time.strftime("%H:%M:%S")

    if selected_time not in slots_data["available_slots"]:
        raise ValueError("Selected appointment slot is not available")

    # Database-level protection against two simultaneous requests taking the same
    # active slot. The index is idempotent and only needs to be created once.
    ensure_active_slot_unique_index(db)

    new_appointment = Appointment(
        hospital_id=request_data.hospital_id,
        doctor_id=request_data.doctor_id,
        patient_id=patient.id,
        appointment_date=request_data.appointment_date,
        appointment_time=request_data.appointment_time,
        reason=request_data.reason,
        status="booked"
    )

    db.add(new_appointment)
    try:
        db.commit()
        db.refresh(new_appointment)
        return _booking_result(new_appointment, doctor, idempotent_replay=False)
    except IntegrityError:
        db.rollback()

        # A concurrent duplicate from this same patient is an idempotent success.
        concurrent_exact = (
            db.query(Appointment)
            .filter(
                Appointment.hospital_id == request_data.hospital_id,
                Appointment.doctor_id == request_data.doctor_id,
                Appointment.patient_id == patient.id,
                Appointment.appointment_date == request_data.appointment_date,
                Appointment.appointment_time == request_data.appointment_time,
                Appointment.status.in_(["booked", "confirmed"]),
            )
            .order_by(Appointment.id.desc())
            .first()
        )
        if concurrent_exact:
            return _booking_result(concurrent_exact, doctor, idempotent_replay=True)

        # Otherwise another patient won the slot between availability check and
        # commit. Report a clean business conflict, not a SQL exception.
        raise ValueError("Selected appointment slot is not available")


def cancel_public_appointment(
    db: Session,
    request_data: PublicCancelAppointmentRequest
):
    appointment, patient = get_verified_public_appointment(
        db=db,
        hospital_id=request_data.hospital_id,
        appointment_id=request_data.appointment_id,
        patient_phone=request_data.patient_phone
    )

    validate_existing_appointment_is_actionable(appointment, "cancel")

    appointment.status = "cancelled"

    db.commit()
    db.refresh(appointment)

    return {
        "message": "Appointment cancelled successfully",
        "appointment_id": appointment.id,
        "patient_id": appointment.patient_id,
        "doctor_id": appointment.doctor_id,
        "appointment_date": appointment.appointment_date,
        "appointment_time": appointment.appointment_time,
        "status": appointment.status
    }


def reschedule_public_appointment(
    db: Session,
    request_data: PublicRescheduleAppointmentRequest
):
    appointment, patient = get_verified_public_appointment(
        db=db,
        hospital_id=request_data.hospital_id,
        appointment_id=request_data.appointment_id,
        patient_phone=request_data.patient_phone
    )

    validate_existing_appointment_is_actionable(appointment, "reschedule")

    validate_not_past_date(request_data.appointment_date)

    if is_past_time_today(
        appointment_date=request_data.appointment_date,
        appointment_time=request_data.appointment_time
    ):
        raise ValueError("You cannot reschedule appointment to a past time")

    doctor = validate_doctor(
        db=db,
        hospital_id=request_data.hospital_id,
        doctor_id=request_data.doctor_id
    )

    # Rescheduling must obey the same one-active-appointment-per-patient,
    # doctor and day rule as creating a new booking. Exclude the appointment
    # being moved, so changing its own time remains allowed.
    other_same_day = find_active_patient_doctor_day_appointment(
        db=db,
        hospital_id=request_data.hospital_id,
        patient_id=appointment.patient_id,
        doctor_id=request_data.doctor_id,
        appointment_date=request_data.appointment_date,
        exclude_appointment_id=appointment.id,
    )
    if other_same_day:
        raise ValueError("You already have an appointment with this doctor on this date")

    slots_data = get_available_slots(
        db=db,
        hospital_id=request_data.hospital_id,
        doctor_id=request_data.doctor_id,
        appointment_date=request_data.appointment_date,
        exclude_appointment_id=appointment.id
    )

    selected_time = request_data.appointment_time.strftime("%H:%M:%S")

    if selected_time not in slots_data["available_slots"]:
        raise ValueError("Selected appointment slot is not available")

    # Ensure the database-level active-slot guard also protects rescheduling.
    # Without this, two concurrent reschedule requests could both pass the
    # availability read before either commits.
    ensure_active_slot_unique_index(db)

    old_doctor_id = appointment.doctor_id
    old_date = appointment.appointment_date
    old_time = appointment.appointment_time

    appointment.doctor_id = request_data.doctor_id
    appointment.appointment_date = request_data.appointment_date
    appointment.appointment_time = request_data.appointment_time
    appointment.status = "booked"

    try:
        db.commit()
        db.refresh(appointment)
    except IntegrityError as exc:
        db.rollback()
        # Restore the ORM object's prior values for callers that continue using
        # this Session after the clean business error is raised.
        appointment.doctor_id = old_doctor_id
        appointment.appointment_date = old_date
        appointment.appointment_time = old_time
        raise ValueError("Selected appointment slot is not available") from exc

    return {
        "message": "Appointment rescheduled successfully",
        "appointment_id": appointment.id,
        "patient_id": appointment.patient_id,
        "doctor_id": doctor.id,
        "doctor_name": doctor.name,
        "appointment_date": appointment.appointment_date,
        "appointment_time": appointment.appointment_time,
        "status": appointment.status
    }

def get_public_appointment_status(
    db: Session,
    request_data
):
    validate_hospital(db, request_data.hospital_id)

    verified_data = get_verified_public_appointment(
        db=db,
        hospital_id=request_data.hospital_id,
        appointment_id=request_data.appointment_id,
        patient_phone=request_data.patient_phone
    )

    if isinstance(verified_data, tuple):
        appointment = verified_data[0]
    else:
        appointment = verified_data

    doctor = validate_doctor(
        db=db,
        hospital_id=request_data.hospital_id,
        doctor_id=appointment.doctor_id
    )

    patient_name = ""

    if appointment.patient:
        patient_name = appointment.patient.name

    return {
        "appointment_id": appointment.id,
        "patient_id": appointment.patient_id,
        "doctor_id": appointment.doctor_id,
        "doctor_name": doctor.name,
        "patient_name": patient_name,
        "appointment_date": appointment.appointment_date,
        "appointment_time": appointment.appointment_time,
        "status": appointment.status,
        "reason": appointment.reason
    }