from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class BookmarkResponse(BaseModel):
    bookmark_id: str
    user_id: str
    document_id: str
    color: str
    content_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CreateBookmarkRequest(BaseModel):
    color: str = "#FFEB3B"
    content_id: int


class UpdateBookmarkRequest(BaseModel):
    color: str


class BatchUpdateBookmarkItem(BaseModel):
    bookmark_id: str
    color: str


class BatchUpdateBookmarkRequest(BaseModel):
    bookmarks: list[BatchUpdateBookmarkItem]


class BookmarkListResponse(BaseModel):
    bookmarks: list[BookmarkResponse]
