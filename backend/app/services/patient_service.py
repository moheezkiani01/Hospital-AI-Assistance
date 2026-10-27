from sqlalchemy.orm import Session

from app.models.hospital import Hospital
from app.models.patient import Patient
from app.schemas.patient import PatientCreate, PatientUpdate


def create_patient(db: Session, patient_data: PatientCreate):
    hospital = (
        db.query(Hospital)
        .filter(Hospital.id == patient_data.hospital_id)
        .first()
    )

    if not hospital:
        raise ValueError("Hospital not found")

    existing_patient = (
        db.query(Patient)
        .filter(
            Patient.hospital_id == patient_data.hospital_id,
            Patient.phone == patient_data.phone
        )
        .first()
    )

    if existing_patient:
        raise ValueError("Patient with this phone number already exists in this hospital")

    new_patient = Patient(**patient_data.model_dump())

    db.add(new_patient)
    db.commit()
    db.refresh(new_patient)

    return new_patient


def get_all_patients(db: Session, hospital_id: int | None = None):
    query = db.query(Patient)

    if hospital_id:
        query = query.filter(Patient.hospital_id == hospital_id)

    return query.all()


def get_patient_by_id(db: Session, patient_id: int):
    return db.query(Patient).filter(Patient.id == patient_id).first()


def update_patient(db: Session, patient_id: int, patient_data: PatientUpdate):
    patient = get_patient_by_id(db, patient_id)

    if not patient:
        return None

    update_data = patient_data.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(patient, key, value)

    db.commit()
    db.refresh(patient)

    return patient


def delete_patient(db: Session, patient_id: int):
    patient = get_patient_by_id(db, patient_id)

    if not patient:
        return None

    db.delete(patient)
    db.commit()

    return patient