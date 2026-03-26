"""
Consumes social-events (post.liked, post.commented, post.reshared, user.followed)
and creates notification DB records + increments Redis unread counter.

Replaces the inline synchronous create_notification() calls in PostService.

Usage:
    python -m workers.notification_worker
"""

import logging

from events.consumer import BaseConsumer
from events.config import CONSUMER_GROUP_NOTIFICATION
from events.topics import SOCIAL_EVENTS, DOCUMENT_EVENTS, SOCIAL_EVENTS_DLQ
from core.db_client import SessionLocal
from notifications.service.notification_service import create_notification

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HANDLED_EVENTS = {
    "post.liked", "post.commented", "post.reshared", "user.followed",
    "document.access_requested",
}


class NotificationWorker(BaseConsumer):
    def __init__(self):
        super().__init__(
            group_id=CONSUMER_GROUP_NOTIFICATION,
            topics=[SOCIAL_EVENTS, DOCUMENT_EVENTS],
            dlq_topic=SOCIAL_EVENTS_DLQ,
            max_retries=3,
        )

    def handle(self, event_type: str, payload: dict) -> None:
        if event_type not in HANDLED_EVENTS:
            return

        db = SessionLocal()
        try:
            if event_type == "post.liked":
                create_notification(
                    db,
                    recipient_id=payload["author_id"],
                    actor_id=payload["actor_id"],
                    notif_type="like",
                    post_id=payload["post_id"],
                    message="liked your post",
                )
            elif event_type == "post.commented":
                create_notification(
                    db,
                    recipient_id=payload["author_id"],
                    actor_id=payload["actor_id"],
                    notif_type="comment",
                    post_id=payload["post_id"],
                    message="commented on your post",
                )
            elif event_type == "post.reshared":
                create_notification(
                    db,
                    recipient_id=payload["author_id"],
                    actor_id=payload["actor_id"],
                    notif_type="reshare",
                    post_id=payload["post_id"],
                    message="reshared your post",
                )
            elif event_type == "user.followed":
                create_notification(
                    db,
                    recipient_id=payload["following_id"],
                    actor_id=payload["follower_id"],
                    notif_type="follow",
                    message="started following you",
                )
            elif event_type == "document.access_requested":
                create_notification(
                    db,
                    recipient_id=payload["owner_id"],
                    actor_id=payload["requester_id"],
                    notif_type="access_request",
                    document_id=payload.get("doc_id"),
                    request_id=payload.get("request_id"),
                    message=f"requested access to {payload.get('document_display_name', 'your document')}",
                )

            logger.info(f"Notification created for {event_type}")
        finally:
            db.close()


if __name__ == "__main__":
    NotificationWorker().start()
