from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    id: int
    hospital_id: int
    uploaded_by_id: Optional[int] = None
    file_name: str
    stored_file_name: str
    file_path: str
    document_type: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentChunkResponse(BaseModel):
    id: int
    hospital_id: int
    document_id: int
    chunk_index: int
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)