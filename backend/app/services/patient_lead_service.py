from typing import Optional

from sqlalchemy.orm import Session

from app.models.hospital import Hospital
from app.models.patient_lead import PatientLead
from app.schemas.patient_lead import PatientLeadCreate, PatientLeadUpdate


def validate_hospital(db: Session, hospital_id: int):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()

    if not hospital:
        raise ValueError("Hospital not found")

    return hospital


def create_patient_lead(
    db: Session,
    request_data: PatientLeadCreate
):
    validate_hospital(db, request_data.hospital_id)

    name = request_data.name.strip()
    phone = request_data.phone.strip()

    if not name:
        raise ValueError("Name is required")

    if not phone:
        raise ValueError("Phone number is required")

    lead = PatientLead(
        hospital_id=request_data.hospital_id,
        name=name,
        phone=phone,
        question=request_data.question,
        interested_service=request_data.interested_service,
        status="new",
        source="chatbot"
    )

    db.add(lead)
    db.commit()
    db.refresh(lead)

    return lead


def get_patient_leads(
    db: Session,
    hospital_id: Optional[int] = None
):
    query = db.query(PatientLead)

    if hospital_id is not None:
        query = query.filter(PatientLead.hospital_id == hospital_id)

    return query.order_by(PatientLead.created_at.desc()).all()


def get_patient_lead_by_id(
    db: Session,
    lead_id: int
):
    lead = (
        db.query(PatientLead)
        .filter(PatientLead.id == lead_id)
        .first()
    )

    if not lead:
        raise ValueError("Patient lead not found")

    return lead


def update_patient_lead(
    db: Session,
    lead_id: int,
    request_data: PatientLeadUpdate
):
    lead = get_patient_lead_by_id(db, lead_id)

    if request_data.name is not None:
        name = request_data.name.strip()

        if not name:
            raise ValueError("Name cannot be empty")

        lead.name = name

    if request_data.phone is not None:
        phone = request_data.phone.strip()

        if not phone:
            raise ValueError("Phone number cannot be empty")

        lead.phone = phone

    if request_data.question is not None:
        lead.question = request_data.question

    if request_data.interested_service is not None:
        lead.interested_service = request_data.interested_service

    if request_data.status is not None:
        lead.status = request_data.status

    if request_data.is_active is not None:
        lead.is_active = request_data.is_active

    db.commit()
    db.refresh(lead)

    return lead


def deactivate_patient_lead(
    db: Session,
    lead_id: int
):
    lead = get_patient_lead_by_id(db, lead_id)

    lead.is_active = False

    db.commit()
    db.refresh(lead)

    return lead