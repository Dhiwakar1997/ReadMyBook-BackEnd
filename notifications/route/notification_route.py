from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from notifications.data.schema import (
    NotificationListResponse,
    UnreadCountResponse,
    MarkReadRequest,
)
from notifications.service.notification_service import NotificationService
from middleware import verify_access_token
from core.db_client import get_db

notification_router = APIRouter(prefix="/notifications", tags=["notifications"])


@notification_router.get(
    "/unread-count",
    response_model=UnreadCountResponse,
    dependencies=[Depends(verify_access_token)],
    summary="Polling endpoint — returns unread notification count (Redis-backed, O(1))",
)
def get_unread_count(request: Request, db: Session = Depends(get_db)):
    """
    Intended for frequent mobile polling (e.g. every 30 s).
    Reads from Redis; falls back to DB only on cache miss.
    """
    return NotificationService(db, request).get_unread_count()


@notification_router.get(
    "",
    response_model=NotificationListResponse,
    dependencies=[Depends(verify_access_token)],
    summary="Fetch paginated notifications for the current user",
)
def get_notifications(
    request: Request,
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 20,
    unread_only: bool = Query(False, description="Return only unread notifications"),
):
    return NotificationService(db, request).get_notifications(
        skip=skip, limit=limit, unread_only=unread_only
    )


@notification_router.patch(
    "/mark-read",
    dependencies=[Depends(verify_access_token)],
    summary="Mark notifications as read and reset Redis counter",
)
def mark_read(request: Request, payload: MarkReadRequest, db: Session = Depends(get_db)):
    """
    Pass `notification_ids` to mark specific notifications.
    Omit (or send null) to mark ALL as read.
    """
    NotificationService(db, request).mark_read(payload.notification_ids)
    return {"message": "Notifications marked as read", "success": True, "status_code": 200}
