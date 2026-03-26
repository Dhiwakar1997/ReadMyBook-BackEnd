"""
Consumes document-events and performs Redis cache invalidation.

Replaces synchronous Redis calls scattered across service methods.

Usage:
    python -m workers.cache_worker
"""

import logging

from events.consumer import BaseConsumer
from events.config import CONSUMER_GROUP_CACHE_INVALIDATION
from events.topics import DOCUMENT_EVENTS, DOCUMENT_EVENTS_DLQ
from shared.redis import RedisService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HANDLED_EVENTS = {
    "document.deleted",
    "document.display_name_changed",
}


class CacheWorker(BaseConsumer):
    def __init__(self):
        super().__init__(
            group_id=CONSUMER_GROUP_CACHE_INVALIDATION,
            topics=[DOCUMENT_EVENTS],
            dlq_topic=DOCUMENT_EVENTS_DLQ,
            max_retries=3,
        )
        self.redis = RedisService()

    def handle(self, event_type: str, payload: dict) -> None:
        if event_type not in HANDLED_EVENTS:
            return

        if event_type == "document.deleted":
            owner_id = payload.get("owner_id", "")
            doc_id = payload.get("doc_id", "")
            if owner_id:
                self.redis.clear_user_cache(owner_id)
            if owner_id and doc_id:
                self.redis.clear_document_cache(owner_id, doc_id)
            if doc_id:
                self.redis.invalidate_doc_meta(doc_id)
            logger.info(f"Cache invalidated for deleted doc={doc_id}")

        elif event_type == "document.display_name_changed":
            doc_id = payload.get("doc_id", "")
            if doc_id:
                self.redis.invalidate_doc_meta(doc_id)
            logger.info(f"Cache invalidated for display_name change doc={doc_id}")


if __name__ == "__main__":
    CacheWorker().start()
