from typing import List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.api.rate_limit_deps import chat_rate_limit
from app.db.database import get_db
from app.models.user import User
from app.schemas.chat import ChatLogResponse, ChatMessageRequest, ChatMessageResponse
from app.services import audit_service, chat_service, llm_monitor_service
from app.services.chat_request_security import sanitize_public_chat_request

router = APIRouter()


@router.post(
    "/message",
    response_model=ChatMessageResponse,
    dependencies=[Depends(chat_rate_limit)],
)
def send_chat_message(
    request_data: ChatMessageRequest,
    db: Session = Depends(get_db)
):
    try:
        request_data = sanitize_public_chat_request(request_data)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error
    request_id = uuid4().hex
    session_id = str(request_data.session_id or "default")[:150]

    try:
        with audit_service.audit_context(
            hospital_id=request_data.hospital_id,
            actor_type="patient_chat",
            session_id=session_id,
            request_id=request_id,
        ), llm_monitor_service.llm_monitor_context(
            hospital_id=request_data.hospital_id,
            session_id=session_id,
            request_id=request_id,
        ):
            return chat_service.handle_chat_message(db, request_data)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error)
        )


@router.get("/logs", response_model=List[ChatLogResponse])
def get_chat_logs(
    hospital_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist"]))
):
    if current_user.hospital_id is not None:
        if hospital_id is not None and hospital_id != current_user.hospital_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this hospital data"
            )

        hospital_id = current_user.hospital_id

    return chat_service.get_chat_logs(db, hospital_id)
