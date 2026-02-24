from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class GetConnectionRequest(BaseModel):
    text: str
    content_id: int


class ConnectedChunk(BaseModel):
    doc_id: str
    text: str
    start_page: int
    end_page: int
    start_content_index: int
    end_content_index: int


class ConnectionResponse(BaseModel):
    connection_id: str
    doc_id: str
    content_id: int
    source_text: str
    connected_chunks: list[ConnectedChunk]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
