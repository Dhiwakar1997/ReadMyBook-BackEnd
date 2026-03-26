"""
One-time script to warm Redis feed caches from PostgreSQL.

For each active user, fetches recent posts from the users they follow
and populates their feed:{user_id} Redis sorted set.

Usage:
    python -m scripts.warm_feed_cache

Safe to re-run — uses ZADD (idempotent) and trims to MAX_FEED_SIZE.
"""

import os
import sys
import time
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.getenv("ENV_FILE", ".env.dev"))

from core.db_client import SessionLocal
from users.data.model import User
from follows.data.model import Follow
from posts.data.model import Post
from shared.redis import RedisService
from fanout_worker.popular_user_service import PopularUserService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAX_FEED_SIZE = 500
BATCH_SIZE = 500


def warm_feed_caches():
    db = SessionLocal()
    redis = RedisService()
    popular_service = PopularUserService()

    try:
        # Get all active user IDs
        user_ids = [
            r[0] for r in db.query(User.user_id)
            .filter(User.is_deleted == False)
            .all()
        ]
        logger.info(f"Found {len(user_ids)} active users")

        warmed = 0
        skipped = 0

        for i, user_id in enumerate(user_ids):
            feed_key = f"feed:{user_id}"

            # Skip if feed already has entries
            existing_count = redis.redis_client.zcard(feed_key)
            if existing_count and existing_count > 0:
                skipped += 1
                if (i + 1) % 100 == 0:
                    logger.info(f"Progress: {i + 1}/{len(user_ids)} (warmed={warmed}, skipped={skipped})")
                continue

            # Get non-popular users this person follows
            following_ids = [
                r[0] for r in db.query(Follow.following_id)
                .filter(Follow.follower_id == user_id)
                .all()
            ]

            if not following_ids:
                skipped += 1
                continue

            # Filter out popular users (their posts are merged at read time)
            non_popular_ids = [
                fid for fid in following_ids
                if not popular_service.is_popular(fid)
            ]

            if not non_popular_ids:
                skipped += 1
                continue

            # Fetch recent posts from non-popular followed users
            posts = (
                db.query(Post.post_id, Post.created_at)
                .filter(
                    Post.author_id.in_(non_popular_ids),
                    Post.is_deleted == False,
                )
                .order_by(Post.created_at.desc())
                .limit(MAX_FEED_SIZE)
                .all()
            )

            if not posts:
                skipped += 1
                continue

            # Batch ZADD to Redis
            pipe = redis.pipeline()
            scores = {p.post_id: p.created_at.timestamp() for p in posts}
            pipe.zadd(feed_key, scores)
            pipe.zremrangebyrank(feed_key, 0, -(MAX_FEED_SIZE + 1))
            pipe.execute()

            warmed += 1
            if (i + 1) % 100 == 0:
                logger.info(f"Progress: {i + 1}/{len(user_ids)} (warmed={warmed}, skipped={skipped})")

        logger.info(f"Done: warmed={warmed}, skipped={skipped}, total={len(user_ids)}")

    finally:
        db.close()


if __name__ == "__main__":
    start = time.time()
    warm_feed_caches()
    elapsed = time.time() - start
    logger.info(f"Feed cache warming completed in {elapsed:.1f}s")
