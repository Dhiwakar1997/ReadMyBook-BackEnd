"""Syncs follow relationships from Kafka events into Neo4j."""

import logging

from core.db_client import SessionLocal
from users.data.repository import UserRepository
from graph.data.graph_repository import GraphRepository

logger = logging.getLogger(__name__)


class GraphSyncService:
    def __init__(self):
        self.graph_repo = GraphRepository()

    def handle_user_followed(self, payload: dict) -> None:
        follower_id = payload.get("follower_id", "")
        following_id = payload.get("following_id", "")
        follow_id = payload.get("follow_id", "")
        timestamp = payload.get("timestamp", 0)
        new_follower_count = payload.get("new_follower_count", 0)

        if not follower_id or not following_id:
            logger.warning("[graph_sync] Missing follower_id or following_id, skipping")
            return

        # Look up both users from PG for node properties
        db = SessionLocal()
        try:
            user_repo = UserRepository(db)
            follower = user_repo.get_user_by_id(follower_id)
            following = user_repo.get_user_by_id(following_id)
        finally:
            db.close()

        # MERGE follower node
        if follower:
            self.graph_repo.merge_user_node(
                user_id=follower.user_id,
                first_name=follower.first_name or "",
                last_name=follower.last_name or "",
                email_id=follower.email_id or "",
                is_verified=follower.is_verified,
                is_private=follower.is_private,
            )
        else:
            # User not found in PG — create minimal node; reconciliation fills gaps
            self.graph_repo.merge_user_node(user_id=follower_id)

        # MERGE following node
        if following:
            self.graph_repo.merge_user_node(
                user_id=following.user_id,
                first_name=following.first_name or "",
                last_name=following.last_name or "",
                email_id=following.email_id or "",
                follower_count=new_follower_count,
                is_verified=following.is_verified,
                is_private=following.is_private,
            )
        else:
            self.graph_repo.merge_user_node(
                user_id=following_id,
                follower_count=new_follower_count,
            )

        # Create the edge
        from datetime import datetime, timezone
        created_at = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat() if timestamp else None
        self.graph_repo.create_follow_edge(
            follower_id=follower_id,
            following_id=following_id,
            follow_id=follow_id,
            created_at=created_at,
        )

        logger.info(f"[graph_sync] FOLLOWS edge created: {follower_id} -> {following_id}")

    def handle_user_unfollowed(self, payload: dict) -> None:
        follower_id = payload.get("follower_id", "")
        following_id = payload.get("following_id", "")

        if not follower_id or not following_id:
            logger.warning("[graph_sync] Missing follower_id or following_id, skipping")
            return

        self.graph_repo.delete_follow_edge(
            follower_id=follower_id,
            following_id=following_id,
        )

        logger.info(f"[graph_sync] FOLLOWS edge deleted: {follower_id} -> {following_id}")
