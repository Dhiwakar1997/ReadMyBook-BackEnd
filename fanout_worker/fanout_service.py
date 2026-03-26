"""Executes fanout-on-write: pushes post_ids to follower feed sorted sets in Redis."""

import logging
import time

from shared.redis import RedisService
from fanout_worker.popular_user_service import PopularUserService
from core.db_client import SessionLocal
from follows.data.repository import FollowRepository

logger = logging.getLogger(__name__)

MAX_FEED_SIZE = 500
PIPELINE_BATCH = 500


class FanoutService:
    def __init__(self):
        self.redis = RedisService()
        self.popular_service = PopularUserService()

    def handle_post_created(self, event: dict) -> None:
        """
        1. Check popular user registry - if popular, skip (fanout-on-read)
        2. Fetch follower IDs from PostgreSQL
        3. Batch ZADD to each follower's feed sorted set
        4. Trim each set to MAX_FEED_SIZE
        """
        author_id = event.get("author_id", "")
        post_id = event.get("post_id", "")
        timestamp = event.get("timestamp", time.time())

        # Check if author is a popular user (skip fanout-on-write)
        is_popular = event.get("is_popular_user", False)
        if not is_popular:
            follower_count = event.get("follower_count", 0)
            is_popular = self.popular_service.is_popular(author_id)

        if is_popular:
            logger.info(f"Skipping fanout-on-write for popular user {author_id}")
            return

        # Fetch follower IDs from DB
        db = SessionLocal()
        try:
            follow_repo = FollowRepository(db)
            followers = follow_repo.get_followers(author_id)
            follower_ids = [f.user_id for f in followers]
        finally:
            db.close()

        if not follower_ids:
            return

        # Batch ZADD using Redis pipelines
        score = timestamp
        for i in range(0, len(follower_ids), PIPELINE_BATCH):
            batch = follower_ids[i:i + PIPELINE_BATCH]
            pipe = self.redis.pipeline()
            for fid in batch:
                feed_key = f"feed:{fid}"
                pipe.zadd(feed_key, {post_id: score})
                pipe.zremrangebyrank(feed_key, 0, -(MAX_FEED_SIZE + 1))
            pipe.execute()

        logger.info(
            f"Fanout complete: post={post_id} -> {len(follower_ids)} followers"
        )

    def handle_post_deleted(self, event: dict) -> None:
        """Remove post_id from all follower feeds."""
        author_id = event.get("author_id", "")
        post_id = event.get("post_id", "")

        if self.popular_service.is_popular(author_id):
            return

        db = SessionLocal()
        try:
            follow_repo = FollowRepository(db)
            followers = follow_repo.get_followers(author_id)
            follower_ids = [f.user_id for f in followers]
        finally:
            db.close()

        if not follower_ids:
            return

        for i in range(0, len(follower_ids), PIPELINE_BATCH):
            batch = follower_ids[i:i + PIPELINE_BATCH]
            pipe = self.redis.pipeline()
            for fid in batch:
                pipe.zrem(f"feed:{fid}", post_id)
            pipe.execute()

        logger.info(
            f"Fanout delete: post={post_id} removed from {len(follower_ids)} feeds"
        )
