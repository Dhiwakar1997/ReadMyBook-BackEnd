"""
Feed cache service using Redis sorted sets.

Supports hybrid fanout:
- Fanout-on-write posts are stored in Redis sorted sets (feed:{user_id})
- Popular user posts are merged at read time from PostgreSQL
"""

import heapq
from typing import Optional

from shared.redis import RedisService
from fanout_worker.popular_user_service import PopularUserService

MAX_FEED_SIZE = 500


class FeedCacheService:
    def __init__(self):
        self.redis = RedisService()
        self.popular_service = PopularUserService()

    def get_cached_feed(self, user_id: str, skip: int = 0,
                        limit: int = 20) -> list[str]:
        """Get post_ids from the user's Redis feed sorted set.

        Returns post_ids ordered by timestamp (newest first).
        """
        feed_key = f"feed:{user_id}"
        try:
            # ZREVRANGE returns highest scores first (newest posts)
            post_ids = self.redis.redis_client.zrevrange(
                feed_key, skip, skip + limit - 1
            )
            return [pid.decode() if isinstance(pid, bytes) else pid
                    for pid in post_ids]
        except Exception as e:
            print(f"[feed_cache] Failed to read feed for {user_id}: {e}")
            return []

    def get_feed_with_popular_merge(
        self,
        user_id: str,
        following_ids: list[str],
        skip: int = 0,
        limit: int = 20,
        db=None,
    ) -> list[str]:
        """Get merged feed: cached fanout-on-write posts + popular user posts.

        1. Get cached feed page (fanout-on-write posts)
        2. For each followed popular user: query PG for their recent posts
        3. Heap merge both lists by timestamp
        4. Apply skip/limit to merged result
        """
        # Get fanout-on-write posts from cache
        cached_posts = self._get_cached_with_scores(user_id, count=skip + limit + 50)

        # Find which followed users are popular
        popular_ids = self.popular_service.get_followed_popular_users(following_ids)

        if not popular_ids or db is None:
            # No popular users followed — just return cached feed
            post_ids = [pid for pid, _ in cached_posts]
            return post_ids[skip:skip + limit]

        # Query recent posts from popular users via PostgreSQL
        popular_posts = self._query_popular_user_posts(db, popular_ids, limit=50)

        # Heap merge: combine cached and popular posts by timestamp (descending)
        merged = list(heapq.merge(
            cached_posts, popular_posts,
            key=lambda x: -x[1],  # negative for descending
        ))

        # Deduplicate (a post could theoretically be in both)
        seen = set()
        deduped = []
        for post_id, score in merged:
            if post_id not in seen:
                seen.add(post_id)
                deduped.append(post_id)

        return deduped[skip:skip + limit]

    def _get_cached_with_scores(self, user_id: str,
                                count: int = 100) -> list[tuple[str, float]]:
        """Get (post_id, score) tuples from Redis sorted set."""
        feed_key = f"feed:{user_id}"
        try:
            results = self.redis.redis_client.zrevrange(
                feed_key, 0, count - 1, withscores=True
            )
            return [
                (pid.decode() if isinstance(pid, bytes) else pid, score)
                for pid, score in results
            ]
        except Exception:
            return []

    def _query_popular_user_posts(self, db, popular_user_ids: list[str],
                                  limit: int = 50) -> list[tuple[str, float]]:
        """Query recent posts from popular users via PostgreSQL.

        Returns (post_id, created_at_timestamp) tuples sorted by timestamp desc.
        ~5ms per user on (author_id, created_at) index.
        """
        from posts.data.model import Post

        try:
            posts = (
                db.query(Post.post_id, Post.created_at)
                .filter(
                    Post.author_id.in_(popular_user_ids),
                    Post.is_deleted == False,
                )
                .order_by(Post.created_at.desc())
                .limit(limit)
                .all()
            )
            return [
                (p.post_id, p.created_at.timestamp())
                for p in posts
            ]
        except Exception as e:
            print(f"[feed_cache] Failed to query popular user posts: {e}")
            return []

    def push_post_to_feed(self, user_id: str, post_id: str,
                          timestamp: float) -> None:
        """Manually push a post to a user's feed (used by fanout worker)."""
        feed_key = f"feed:{user_id}"
        try:
            pipe = self.redis.pipeline()
            pipe.zadd(feed_key, {post_id: timestamp})
            pipe.zremrangebyrank(feed_key, 0, -(MAX_FEED_SIZE + 1))
            pipe.execute()
        except Exception as e:
            print(f"[feed_cache] Failed to push to feed {user_id}: {e}")

    def remove_post_from_feed(self, user_id: str, post_id: str) -> None:
        """Remove a post from a user's feed."""
        feed_key = f"feed:{user_id}"
        try:
            self.redis.redis_client.zrem(feed_key, post_id)
        except Exception as e:
            print(f"[feed_cache] Failed to remove from feed {user_id}: {e}")
