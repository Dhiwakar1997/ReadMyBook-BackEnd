"""
Consumes document-events (document.display_name_changed) and propagates
the new display name to all posts referencing that document.

Replaces background thread in document_service.py update_document().

Usage:
    python -m workers.display_name_worker
"""

import logging

from events.consumer import BaseConsumer
from events.config import CONSUMER_GROUP_DISPLAY_NAME
from events.topics import DOCUMENT_EVENTS, DOCUMENT_EVENTS_DLQ
from core.db_client import SessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DisplayNameWorker(BaseConsumer):
    def __init__(self):
        super().__init__(
            group_id=CONSUMER_GROUP_DISPLAY_NAME,
            topics=[DOCUMENT_EVENTS],
            dlq_topic=DOCUMENT_EVENTS_DLQ,
            max_retries=3,
        )

    def handle(self, event_type: str, payload: dict) -> None:
        if event_type != "document.display_name_changed":
            return

        from posts.data.repository import PostRepository

        doc_id = payload.get("doc_id", "")
        new_name = payload.get("new_name", "")

        db = SessionLocal()
        try:
            PostRepository(db).update_display_name_for_doc(doc_id, new_name)
            logger.info(f"Display name propagated for doc={doc_id} -> '{new_name}'")
        finally:
            db.close()


if __name__ == "__main__":
    DisplayNameWorker().start()
