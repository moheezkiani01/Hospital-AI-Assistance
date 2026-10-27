from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.database import get_db
from app.models.user import User
from app.schemas.document import DocumentChunkResponse, DocumentResponse
from app.services import document_service

router = APIRouter()


def check_hospital_permission(current_user: User, hospital_id: int):
    if current_user.hospital_id is not None and current_user.hospital_id != hospital_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this hospital data"
        )


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def upload_document(
    hospital_id: int = Form(...),
    document_type: Optional[str] = Form(default=None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin"]))
):
    check_hospital_permission(current_user, hospital_id)

    try:
        return document_service.upload_document(
            db=db,
            hospital_id=hospital_id,
            uploaded_by_id=current_user.id,
            file=file,
            document_type=document_type
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error)
        )


@router.get("/", response_model=List[DocumentResponse])
def get_documents(
    hospital_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.hospital_id is not None:
        if hospital_id is not None and hospital_id != current_user.hospital_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this hospital data"
            )

        hospital_id = current_user.hospital_id

    return document_service.get_all_documents(db, hospital_id)


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    document = document_service.get_document_by_id(db, document_id)

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    check_hospital_permission(current_user, document.hospital_id)

    return document


@router.get("/{document_id}/chunks", response_model=List[DocumentChunkResponse])
def get_document_chunks(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    document = document_service.get_document_by_id(db, document_id)

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    check_hospital_permission(current_user, document.hospital_id)

    return document_service.get_chunks_by_document_id(db, document_id)


@router.delete("/{document_id}", response_model=DocumentResponse)
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin"]))
):
    document = document_service.get_document_by_id(db, document_id)

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    check_hospital_permission(current_user, document.hospital_id)

    deleted_document = document_service.delete_document(db, document_id)

    return deleted_document