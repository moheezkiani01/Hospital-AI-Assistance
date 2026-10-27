from sqlalchemy.orm import Session

from app.models.hospital import Hospital
from app.schemas.hospital import HospitalCreate, HospitalUpdate


def create_hospital(db: Session, hospital_data: HospitalCreate):
    existing_hospital = (
        db.query(Hospital)
        .filter(Hospital.name == hospital_data.name)
        .first()
    )

    if existing_hospital:
        raise ValueError("Hospital with this name already exists")

    new_hospital = Hospital(**hospital_data.model_dump())

    db.add(new_hospital)
    db.commit()
    db.refresh(new_hospital)

    return new_hospital


def get_all_hospitals(db: Session):
    return db.query(Hospital).all()


def get_hospital_by_id(db: Session, hospital_id: int):
    return db.query(Hospital).filter(Hospital.id == hospital_id).first()


def update_hospital(db: Session, hospital_id: int, hospital_data: HospitalUpdate):
    hospital = get_hospital_by_id(db, hospital_id)

    if not hospital:
        return None

    update_data = hospital_data.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(hospital, key, value)

    db.commit()
    db.refresh(hospital)

    return hospital


def delete_hospital(db: Session, hospital_id: int):
    hospital = get_hospital_by_id(db, hospital_id)

    if not hospital:
        return None

    hospital.is_active = False
    db.commit()
    db.refresh(hospital)

    return hospital