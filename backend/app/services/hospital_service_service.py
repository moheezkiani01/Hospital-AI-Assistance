from typing import Optional

from sqlalchemy.orm import Session

from app.models.department import Department
from app.models.hospital import Hospital
from app.models.hospital_service import HospitalService
from app.schemas.hospital_service import HospitalServiceCreate, HospitalServiceUpdate


def validate_hospital(db: Session, hospital_id: int):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()

    if not hospital:
        raise ValueError("Hospital not found")

    return hospital


def validate_department(db: Session, hospital_id: int, department_id: Optional[int]):
    if department_id is None:
        return None

    department = (
        db.query(Department)
        .filter(
            Department.id == department_id,
            Department.hospital_id == hospital_id
        )
        .first()
    )

    if not department:
        raise ValueError("Department not found")

    return department


def create_hospital_service(db: Session, request_data: HospitalServiceCreate):
    validate_hospital(db, request_data.hospital_id)
    validate_department(db, request_data.hospital_id, request_data.department_id)

    existing_service = (
        db.query(HospitalService)
        .filter(
            HospitalService.hospital_id == request_data.hospital_id,
            HospitalService.name == request_data.name
        )
        .first()
    )

    if existing_service:
        raise ValueError("Service with this name already exists")

    hospital_service = HospitalService(
        hospital_id=request_data.hospital_id,
        department_id=request_data.department_id,
        name=request_data.name.strip(),
        description=request_data.description
    )

    db.add(hospital_service)
    db.commit()
    db.refresh(hospital_service)

    return hospital_service


def get_hospital_services(db: Session, hospital_id: Optional[int] = None):
    query = db.query(HospitalService)

    if hospital_id is not None:
        query = query.filter(HospitalService.hospital_id == hospital_id)

    return query.order_by(HospitalService.name.asc()).all()


def get_active_hospital_services(db: Session, hospital_id: int):
    return (
        db.query(HospitalService)
        .filter(
            HospitalService.hospital_id == hospital_id,
            HospitalService.is_active == True
        )
        .order_by(HospitalService.name.asc())
        .all()
    )


def get_hospital_service_by_id(db: Session, service_id: int):
    hospital_service = (
        db.query(HospitalService)
        .filter(HospitalService.id == service_id)
        .first()
    )

    if not hospital_service:
        raise ValueError("Service not found")

    return hospital_service


def update_hospital_service(
    db: Session,
    service_id: int,
    request_data: HospitalServiceUpdate
):
    hospital_service = get_hospital_service_by_id(db, service_id)

    if request_data.department_id is not None:
        validate_department(
            db=db,
            hospital_id=hospital_service.hospital_id,
            department_id=request_data.department_id
        )
        hospital_service.department_id = request_data.department_id

    if request_data.name is not None:
        hospital_service.name = request_data.name.strip()

    if request_data.description is not None:
        hospital_service.description = request_data.description

    if request_data.is_active is not None:
        hospital_service.is_active = request_data.is_active

    db.commit()
    db.refresh(hospital_service)

    return hospital_service


def delete_hospital_service(db: Session, service_id: int):
    hospital_service = get_hospital_service_by_id(db, service_id)

    hospital_service.is_active = False

    db.commit()
    db.refresh(hospital_service)

    return hospital_service