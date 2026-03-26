"""Manages the popular user registry in Redis for hybrid fanout strategy."""

from shared.redis import RedisService
from events.config import POPULAR_USER_THRESHOLD

POPULAR_USER_KEY = "popular:users"


class PopularUserService:
    def __init__(self):
        self.redis = RedisService()
        self.threshold = POPULAR_USER_THRESHOLD

    def is_popular(self, user_id: str) -> bool:
        """Check if a user is in the popular user set. O(1) SISMEMBER."""
        try:
            return bool(self.redis.redis_client.sismember(POPULAR_USER_KEY, user_id))
        except Exception:
            return False

    def update_registry(self, user_id: str, follower_count: int) -> None:
        """Add or remove a user from the popular set based on follower count."""
        try:
            if follower_count >= self.threshold:
                self.redis.redis_client.sadd(POPULAR_USER_KEY, user_id)
            else:
                self.redis.redis_client.srem(POPULAR_USER_KEY, user_id)
        except Exception as e:
            print(f"[popular_user] Failed to update registry for {user_id}: {e}")

    def get_followed_popular_users(self, following_ids: list[str]) -> list[str]:
        """Return the subset of following_ids that are in the popular user set.

        Uses SINTER-like logic but checks individually to avoid building
        a temporary set. For typical users following <10 popular accounts,
        this is 0-10 SISMEMBER calls.
        """
        popular = []
        for uid in following_ids:
            if self.is_popular(uid):
                popular.append(uid)
        return popular
