from typing import List

from pydantic import BaseModel


class RAGQuestionRequest(BaseModel):
    hospital_id: int
    question: str


class RAGSource(BaseModel):
    document_id: int
    chunk_id: int
    chunk_index: int
    content: str
    score: int


class RAGQuestionResponse(BaseModel):
    question: str
    answer: str
    sources: List[RAGSource]