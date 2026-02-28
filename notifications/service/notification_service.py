import ulid
import datetime
from typing import Optional

from sqlalchemy.orm import Session
from fastapi import Request

from shared.redis import RedisService
from notifications.data.model import Notification
from notifications.data.repository import NotificationRepository
from notifications.data.schema import (
    NotificationListResponse,
    NotificationResponse,
    UnreadCountResponse,
)


def _unread_key(user_id: str) -> str:
    return f"notif:unread:{user_id}"


# ── Standalone helper ─────────────────────────────────────────────────────────

def create_notification(
    db: Session,
    recipient_id: str,
    actor_id: str,
    notif_type: str,
    post_id: Optional[str] = None,
    document_id: Optional[str] = None,
    request_id: Optional[str] = None,
    message: Optional[str] = None,
) -> None:
    """
    Fire-and-forget helper. Import this from any service to create a notification.
    - Never self-notifies (recipient == actor is silently skipped).
    - Swallows all errors so the parent operation is never disrupted.
    """
    if recipient_id == actor_id:
        return

    try:
        notif = Notification(
            notification_id="notif_" + str(ulid.new()),
            recipient_id=recipient_id,
            actor_id=actor_id,
            type=notif_type,
            post_id=post_id,
            document_id=document_id,
            request_id=request_id,
            message=message,
            created_at=datetime.datetime.utcnow(),
        )
        db.add(notif)
        db.commit()

        # Increment Redis unread counter atomically
        try:
            RedisService().increment(_unread_key(recipient_id))
        except Exception:
            pass  # Redis failure must never block the main flow

    except Exception as e:
        db.rollback()
        print(f"[notification] Failed to create notification: {e}")


# ── Service class (for API layer) ─────────────────────────────────────────────

class NotificationService:
    def __init__(self, db: Session, request: Request):
        self.db = db
        self.request = request
        self.repo = NotificationRepository(db)
        self.user_id = request.state.user_id

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_notifications(
        self,
        skip: int = 0,
        limit: int = 20,
        unread_only: bool = False,
    ) -> NotificationListResponse:
        rows, total = self.repo.get_for_user(
            self.user_id, skip=skip, limit=limit, unread_only=unread_only
        )
        notifications = [
            NotificationResponse(
                notification_id=row["notification"].notification_id,
                type=row["notification"].type,
                actor_id=row["actor"].user_id,
                actor_first_name=row["actor"].first_name,
                actor_last_name=row["actor"].last_name,
                post_id=row["notification"].post_id,
                document_id=row["notification"].document_id,
                request_id=row["notification"].request_id,
                message=row["notification"].message,
                is_read=row["notification"].is_read,
                created_at=row["notification"].created_at,
            )
            for row in rows
        ]
        return NotificationListResponse(
            notifications=notifications,
            total=total,
            unread_count=self._redis_count(),
            skip=skip,
            limit=limit,
        )

    def get_unread_count(self) -> UnreadCountResponse:
        return UnreadCountResponse(unread_count=self._redis_count())

    # ── Mutations ─────────────────────────────────────────────────────────────

    def mark_read(self, notification_ids: Optional[list[str]] = None) -> None:
        if notification_ids:
            self.repo.mark_read(notification_ids, self.user_id)
        else:
            self.repo.mark_all_read(self.user_id)
        # Sync Redis counter with actual DB state
        actual = self.repo.get_unread_count_from_db(self.user_id)
        self._set_redis_count(actual)

    # ── Redis helpers ─────────────────────────────────────────────────────────

    def _redis_count(self) -> int:
        try:
            redis = RedisService()
            val = redis.get_value(_unread_key(self.user_id))
            if val is None:
                # Cold cache: prime from DB
                count = self.repo.get_unread_count_from_db(self.user_id)
                self._set_redis_count(count)
                return count
            return int(val)
        except Exception:
            return self.repo.get_unread_count_from_db(self.user_id)

    def _set_redis_count(self, count: int) -> None:
        try:
            # TTL: 7 days — refreshed on every write
            RedisService().set_value(_unread_key(self.user_id), count, ttl=60 * 60 * 24 * 7)
        except Exception:
            pass
