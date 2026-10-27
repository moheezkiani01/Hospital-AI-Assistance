from sqlalchemy.orm import Session

from app.models.doctor import Doctor
from app.models.hospital import Hospital
from app.schemas.doctor import DoctorCreate, DoctorUpdate


def create_doctor(db: Session, doctor_data: DoctorCreate):
    hospital = (
        db.query(Hospital)
        .filter(Hospital.id == doctor_data.hospital_id)
        .first()
    )

    if not hospital:
        raise ValueError("Hospital not found")

    new_doctor = Doctor(**doctor_data.model_dump())

    db.add(new_doctor)
    db.commit()
    db.refresh(new_doctor)

    return new_doctor


def get_all_doctors(db: Session, hospital_id: int | None = None):
    query = db.query(Doctor)

    if hospital_id:
        query = query.filter(Doctor.hospital_id == hospital_id)

    return query.all()


def get_doctor_by_id(db: Session, doctor_id: int):
    return db.query(Doctor).filter(Doctor.id == doctor_id).first()


def update_doctor(db: Session, doctor_id: int, doctor_data: DoctorUpdate):
    doctor = get_doctor_by_id(db, doctor_id)

    if not doctor:
        return None

    update_data = doctor_data.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(doctor, key, value)

    db.commit()
    db.refresh(doctor)

    return doctor


def delete_doctor(db: Session, doctor_id: int):
    doctor = get_doctor_by_id(db, doctor_id)

    if not doctor:
        return None

    doctor.is_active = False
    db.commit()
    db.refresh(doctor)

    return doctor