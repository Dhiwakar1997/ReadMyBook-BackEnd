from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class WordExplanationItem(BaseModel):
    explanation_id: str
    doc_id: str
    user_id: str
    word: str
    content_id: int
    page_id: int
    ai_explanation: str
    created_at: datetime

    class Config:
        from_attributes = True


class WordExplanationsResponse(BaseModel):
    explanations: list[WordExplanationItem]
    total: int
    page_offset: int
    window_size: int
