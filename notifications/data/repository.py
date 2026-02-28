from sqlalchemy.orm import Session
from sqlalchemy import func

from notifications.data.model import Notification
from users.data.model import User


class NotificationRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, notif: Notification) -> Notification:
        self.db.add(notif)
        self.db.commit()
        self.db.refresh(notif)
        return notif

    def get_for_user(
        self,
        user_id: str,
        skip: int = 0,
        limit: int = 20,
        unread_only: bool = False,
    ) -> tuple[list[dict], int]:
        base_q = (
            self.db.query(Notification, User)
            .join(User, User.user_id == Notification.actor_id)
            .filter(Notification.recipient_id == user_id)
        )
        if unread_only:
            base_q = base_q.filter(Notification.is_read == False)
        base_q = base_q.order_by(Notification.created_at.desc())

        total = base_q.count()
        rows = base_q.offset(skip).limit(limit).all()

        return [{"notification": n, "actor": a} for n, a in rows], total

    def mark_all_read(self, user_id: str) -> int:
        count = (
            self.db.query(Notification)
            .filter(
                Notification.recipient_id == user_id,
                Notification.is_read == False,
            )
            .update({"is_read": True}, synchronize_session="fetch")
        )
        self.db.commit()
        return count

    def mark_read(self, notification_ids: list[str], user_id: str) -> int:
        count = (
            self.db.query(Notification)
            .filter(
                Notification.notification_id.in_(notification_ids),
                Notification.recipient_id == user_id,
            )
            .update({"is_read": True}, synchronize_session="fetch")
        )
        self.db.commit()
        return count

    def get_unread_count_from_db(self, user_id: str) -> int:
        return self.db.query(func.count(Notification.notification_id)).filter(
            Notification.recipient_id == user_id,
            Notification.is_read == False,
        ).scalar() or 0
