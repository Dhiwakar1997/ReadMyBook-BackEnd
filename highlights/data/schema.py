from pydantic import BaseModel
from datetime import datetime


class HighlightResponse(BaseModel):
    highlight_id: str
    user_id: str
    document_id: str
    content_id: int
    page_number: int
    start_index: int
    stop_index: int
    highlight_color: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CreateHighlightRequest(BaseModel):
    content_id: int
    page_number: int
    start_index: int
    stop_index: int
    highlight_color: str = "#FFEB3B"


class UpdateHighlightRequest(BaseModel):
    start_index: int
    stop_index: int


class HighlightListResponse(BaseModel):
    highlights: list[HighlightResponse]
