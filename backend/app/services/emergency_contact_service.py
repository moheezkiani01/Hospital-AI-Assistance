from typing import Optional

from sqlalchemy.orm import Session

from app.models.emergency_contact import EmergencyContact
from app.models.hospital import Hospital
from app.schemas.emergency_contact import (
    EmergencyContactCreate,
    EmergencyContactUpdate
)


def validate_hospital(db: Session, hospital_id: int):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()

    if not hospital:
        raise ValueError("Hospital not found")

    return hospital


def create_emergency_contact(
    db: Session,
    request_data: EmergencyContactCreate
):
    validate_hospital(db, request_data.hospital_id)

    title = request_data.title.strip()
    phone_number = request_data.phone_number.strip()

    if not title:
        raise ValueError("Contact title is required")

    if not phone_number:
        raise ValueError("Phone number is required")

    existing_contact = (
        db.query(EmergencyContact)
        .filter(
            EmergencyContact.hospital_id == request_data.hospital_id,
            EmergencyContact.title == title,
            EmergencyContact.phone_number == phone_number
        )
        .first()
    )

    if existing_contact:
        raise ValueError("Emergency contact with this title and phone number already exists")

    emergency_contact = EmergencyContact(
        hospital_id=request_data.hospital_id,
        title=title,
        phone_number=phone_number,
        contact_type=request_data.contact_type,
        description=request_data.description
    )

    db.add(emergency_contact)
    db.commit()
    db.refresh(emergency_contact)

    return emergency_contact


def get_emergency_contacts(
    db: Session,
    hospital_id: Optional[int] = None
):
    query = db.query(EmergencyContact)

    if hospital_id is not None:
        query = query.filter(EmergencyContact.hospital_id == hospital_id)

    return query.order_by(EmergencyContact.title.asc()).all()


def get_active_emergency_contacts(
    db: Session,
    hospital_id: int
):
    return (
        db.query(EmergencyContact)
        .filter(
            EmergencyContact.hospital_id == hospital_id,
            EmergencyContact.is_active == True
        )
        .order_by(EmergencyContact.title.asc())
        .all()
    )


def get_emergency_contact_by_id(
    db: Session,
    contact_id: int
):
    emergency_contact = (
        db.query(EmergencyContact)
        .filter(EmergencyContact.id == contact_id)
        .first()
    )

    if not emergency_contact:
        raise ValueError("Emergency contact not found")

    return emergency_contact


def update_emergency_contact(
    db: Session,
    contact_id: int,
    request_data: EmergencyContactUpdate
):
    emergency_contact = get_emergency_contact_by_id(db, contact_id)

    if request_data.title is not None:
        title = request_data.title.strip()

        if not title:
            raise ValueError("Contact title cannot be empty")

        emergency_contact.title = title

    if request_data.phone_number is not None:
        phone_number = request_data.phone_number.strip()

        if not phone_number:
            raise ValueError("Phone number cannot be empty")

        emergency_contact.phone_number = phone_number

    if request_data.contact_type is not None:
        emergency_contact.contact_type = request_data.contact_type

    if request_data.description is not None:
        emergency_contact.description = request_data.description

    if request_data.is_active is not None:
        emergency_contact.is_active = request_data.is_active

    db.commit()
    db.refresh(emergency_contact)

    return emergency_contact


def delete_emergency_contact(
    db: Session,
    contact_id: int
):
    emergency_contact = get_emergency_contact_by_id(db, contact_id)

    emergency_contact.is_active = False

    db.commit()
    db.refresh(emergency_contact)

    return emergency_contact