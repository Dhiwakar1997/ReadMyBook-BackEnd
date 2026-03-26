"""
Kafka consumer for feed fanout.

Consumes social-events (post.created, post.deleted) and pushes post_ids
to follower feed sorted sets in Redis.

Also consumes user.followed/user.unfollowed to maintain the popular user registry.

Usage:
    python -m fanout_worker.consumer
"""

import logging

from events.consumer import BaseConsumer
from events.config import CONSUMER_GROUP_FEED_FANOUT
from events.topics import SOCIAL_EVENTS, SOCIAL_EVENTS_DLQ
from fanout_worker.fanout_service import FanoutService
from fanout_worker.popular_user_service import PopularUserService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FanoutConsumer(BaseConsumer):
    def __init__(self):
        super().__init__(
            group_id=CONSUMER_GROUP_FEED_FANOUT,
            topics=[SOCIAL_EVENTS],
            dlq_topic=SOCIAL_EVENTS_DLQ,
            max_retries=3,
        )
        self.fanout_service = FanoutService()
        self.popular_service = PopularUserService()

    def handle(self, event_type: str, payload: dict) -> None:
        if event_type == "post.created":
            self.fanout_service.handle_post_created(payload)

        elif event_type == "post.deleted":
            self.fanout_service.handle_post_deleted(payload)

        elif event_type in ("user.followed", "user.unfollowed"):
            # Update popular user registry based on new follower count
            following_id = payload.get("following_id", "")
            new_count = payload.get("new_follower_count", 0)
            self.popular_service.update_registry(following_id, new_count)
            logger.info(
                f"Popular registry updated: user={following_id} count={new_count}"
            )


if __name__ == "__main__":
    FanoutConsumer().start()
