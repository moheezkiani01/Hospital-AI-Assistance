from typing import Optional

from sqlalchemy.orm import Session

from app.models.department import Department
from app.models.hospital import Hospital
from app.models.lab_test import LabTest
from app.schemas.lab_test import LabTestCreate, LabTestUpdate


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


def create_lab_test(db: Session, request_data: LabTestCreate):
    validate_hospital(db, request_data.hospital_id)
    validate_department(db, request_data.hospital_id, request_data.department_id)

    existing_lab_test = (
        db.query(LabTest)
        .filter(
            LabTest.hospital_id == request_data.hospital_id,
            LabTest.name == request_data.name
        )
        .first()
    )

    if existing_lab_test:
        raise ValueError("Lab test with this name already exists")

    lab_test = LabTest(
        hospital_id=request_data.hospital_id,
        department_id=request_data.department_id,
        name=request_data.name.strip(),
        description=request_data.description,
        price=request_data.price,
        sample_type=request_data.sample_type,
        report_time=request_data.report_time
    )

    db.add(lab_test)
    db.commit()
    db.refresh(lab_test)

    return lab_test


def get_lab_tests(db: Session, hospital_id: Optional[int] = None):
    query = db.query(LabTest)

    if hospital_id is not None:
        query = query.filter(LabTest.hospital_id == hospital_id)

    return query.order_by(LabTest.name.asc()).all()


def get_active_lab_tests(db: Session, hospital_id: int):
    return (
        db.query(LabTest)
        .filter(
            LabTest.hospital_id == hospital_id,
            LabTest.is_active == True
        )
        .order_by(LabTest.name.asc())
        .all()
    )


def get_lab_test_by_id(db: Session, lab_test_id: int):
    lab_test = db.query(LabTest).filter(LabTest.id == lab_test_id).first()

    if not lab_test:
        raise ValueError("Lab test not found")

    return lab_test


def update_lab_test(db: Session, lab_test_id: int, request_data: LabTestUpdate):
    lab_test = get_lab_test_by_id(db, lab_test_id)

    if request_data.department_id is not None:
        validate_department(
            db=db,
            hospital_id=lab_test.hospital_id,
            department_id=request_data.department_id
        )
        lab_test.department_id = request_data.department_id

    if request_data.name is not None:
        lab_test.name = request_data.name.strip()

    if request_data.description is not None:
        lab_test.description = request_data.description

    if request_data.price is not None:
        lab_test.price = request_data.price

    if request_data.sample_type is not None:
        lab_test.sample_type = request_data.sample_type

    if request_data.report_time is not None:
        lab_test.report_time = request_data.report_time

    if request_data.is_active is not None:
        lab_test.is_active = request_data.is_active

    db.commit()
    db.refresh(lab_test)

    return lab_test


def delete_lab_test(db: Session, lab_test_id: int):
    lab_test = get_lab_test_by_id(db, lab_test_id)

    lab_test.is_active = False

    db.commit()
    db.refresh(lab_test)

    return lab_test