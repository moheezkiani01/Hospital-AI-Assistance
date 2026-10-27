from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from datetime import date

from app.models.appointment import Appointment
from app.models.doctor import Doctor
from app.models.hospital import Hospital
from app.models.patient import Patient
from app.services import public_booking_service
from app.schemas.appointment import AppointmentCreate, AppointmentUpdate


ACTIVE_APPOINTMENT_STATUSES = ["booked", "confirmed"]
ALLOWED_APPOINTMENT_STATUSES = {"booked", "confirmed", "cancelled", "completed", "no_show"}
TERMINAL_APPOINTMENT_STATUSES = {"cancelled", "completed", "no_show"}


def create_appointment(db: Session, appointment_data: AppointmentCreate):
    """Staff and public bookings share the same slot and date rules."""
    public_booking_service.validate_not_past_date(appointment_data.appointment_date)
    if public_booking_service.is_past_time_today(
        appointment_data.appointment_date, appointment_data.appointment_time
    ):
        raise ValueError("You cannot book an appointment for a past time")

    hospital = db.query(Hospital).filter(Hospital.id == appointment_data.hospital_id).first()
    if not hospital:
        raise ValueError("Hospital not found")

    doctor = (
        db.query(Doctor)
        .filter(
            Doctor.id == appointment_data.doctor_id,
            Doctor.hospital_id == appointment_data.hospital_id,
            Doctor.is_active == True,
        )
        .first()
    )
    if not doctor:
        raise ValueError("Doctor not found in this hospital")

    patient = (
        db.query(Patient)
        .filter(
            Patient.id == appointment_data.patient_id,
            Patient.hospital_id == appointment_data.hospital_id,
        )
        .first()
    )
    if not patient:
        raise ValueError("Patient not found in this hospital")

    # The public booking path already enforces one active appointment per
    # patient, doctor and day. Match that rule for staff-created appointments.
    existing_same_day = (
        db.query(Appointment)
        .filter(
            Appointment.hospital_id == appointment_data.hospital_id,
            Appointment.doctor_id == appointment_data.doctor_id,
            Appointment.patient_id == appointment_data.patient_id,
            Appointment.appointment_date == appointment_data.appointment_date,
            Appointment.status.in_(ACTIVE_APPOINTMENT_STATUSES),
        )
        .first()
    )
    if existing_same_day:
        raise ValueError("Patient already has an appointment with this doctor on this date")

    availability = public_booking_service.get_available_slots(
        db=db,
        hospital_id=appointment_data.hospital_id,
        doctor_id=appointment_data.doctor_id,
        appointment_date=appointment_data.appointment_date,
    )
    selected_time = appointment_data.appointment_time.strftime("%H:%M:%S")
    if selected_time not in availability["available_slots"]:
        raise ValueError("Selected appointment slot is not available")

    # The same database uniqueness protection used by public booking prevents
    # two simultaneous writes from silently reserving the same active slot.
    public_booking_service.ensure_active_slot_unique_index(db)

    new_appointment = Appointment(**appointment_data.model_dump(), status="booked")
    db.add(new_appointment)
    try:
        db.commit()
        db.refresh(new_appointment)
    except IntegrityError as error:
        db.rollback()
        raise ValueError("Selected appointment slot is not available") from error
    return new_appointment


def get_all_appointments(
    db: Session,
    hospital_id: Optional[int] = None,
    doctor_id: Optional[int] = None,
    patient_id: Optional[int] = None
):
    query = db.query(Appointment)

    if hospital_id:
        query = query.filter(Appointment.hospital_id == hospital_id)

    if doctor_id:
        query = query.filter(Appointment.doctor_id == doctor_id)

    if patient_id:
        query = query.filter(Appointment.patient_id == patient_id)

    return query.all()


def get_appointment_by_id(db: Session, appointment_id: int):
    return (
        db.query(Appointment)
        .filter(Appointment.id == appointment_id)
        .first()
    )


def update_appointment(
    db: Session,
    appointment_id: int,
    appointment_data: AppointmentUpdate
):
    appointment = get_appointment_by_id(db, appointment_id)
    if not appointment:
        return None

    update_data = appointment_data.model_dump(exclude_unset=True)
    if "status" in update_data:
        proposed_status = update_data["status"]
        if proposed_status not in ALLOWED_APPOINTMENT_STATUSES:
            raise ValueError("Invalid appointment status")

        existing_status = str(appointment.status or "").strip().lower()
        if (existing_status in TERMINAL_APPOINTMENT_STATUSES
                and proposed_status != existing_status):
            raise ValueError("Cannot reactivate or change a terminal appointment")

    for key, value in update_data.items():
        setattr(appointment, key, value)

    try:
        db.commit()
        db.refresh(appointment)
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("Appointment status conflicts with an existing active slot") from exc

    return appointment


def cancel_appointment(db: Session, appointment_id: int):
    appointment = get_appointment_by_id(db, appointment_id)
    if not appointment:
        return None

    public_booking_service.validate_existing_appointment_is_actionable(
        appointment, "cancel"
    )
    appointment.status = "cancelled"

    try:
        db.commit()
        db.refresh(appointment)
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("Could not cancel this appointment") from exc

    return appointment


def get_available_slots(
    db: Session,
    hospital_id: int,
    doctor_id: int,
    appointment_date: date,
):
    """Display exactly the slots the booking service will accept."""
    public_booking_service.validate_not_past_date(appointment_date)
    return public_booking_service.get_available_slots(
        db=db,
        hospital_id=hospital_id,
        doctor_id=doctor_id,
        appointment_date=appointment_date,
    )
