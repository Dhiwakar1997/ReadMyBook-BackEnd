from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class NotificationResponse(BaseModel):
    notification_id: str
    type: str
    actor_id: str
    actor_first_name: str
    actor_last_name: Optional[str] = None
    post_id: Optional[str] = None
    document_id: Optional[str] = None
    request_id: Optional[str] = None
    message: Optional[str] = None
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class NotificationListResponse(BaseModel):
    notifications: list[NotificationResponse]
    total: int
    unread_count: int
    skip: int
    limit: int


class UnreadCountResponse(BaseModel):
    unread_count: int


class MarkReadRequest(BaseModel):
    # if None or empty list → mark ALL as read
    notification_ids: Optional[list[str]] = None
