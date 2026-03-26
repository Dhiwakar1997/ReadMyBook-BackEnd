"""
Kafka consumer for Neo4j graph sync.

Consumes social-events (user.followed, user.unfollowed) and syncs
follow relationships into Neo4j.

Usage:
    python -m graph_sync_worker
"""

import logging

from events.consumer import BaseConsumer
from events.config import CONSUMER_GROUP_GRAPH_SYNC
from events.topics import SOCIAL_EVENTS, SOCIAL_EVENTS_DLQ
from graph_sync_worker.graph_sync_service import GraphSyncService
from shared.neo4j import Neo4jService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class GraphSyncConsumer(BaseConsumer):
    def __init__(self):
        super().__init__(
            group_id=CONSUMER_GROUP_GRAPH_SYNC,
            topics=[SOCIAL_EVENTS],
            dlq_topic=SOCIAL_EVENTS_DLQ,
            max_retries=3,
        )
        neo4j = Neo4jService()
        if not neo4j.is_available():
            logger.warning("[graph_sync] Neo4j not available — events will be retried/DLQ'd")
        self.sync_service = GraphSyncService()

    def handle(self, event_type: str, payload: dict) -> None:
        if event_type == "user.followed":
            self.sync_service.handle_user_followed(payload)
        elif event_type == "user.unfollowed":
            self.sync_service.handle_user_unfollowed(payload)


if __name__ == "__main__":
    GraphSyncConsumer().start()
