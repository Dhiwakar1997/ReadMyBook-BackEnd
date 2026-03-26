# Fanout Architecture with Kafka

## Context

Post creation currently runs synchronously — no async fan-out to followers. The feed cache (see `feed-cache-strategy.md`) uses in-process background threads for push. This plan replaces that with Kafka-based event streaming and a dedicated fanout worker, with a hybrid strategy: fanout-on-write for normal users, fanout-on-read for popular users (100K+ followers).

**Prerequisite:** Feed Cache (Task 2) must be deployed first. This task replaces its in-process background thread with Kafka consumers.

---

## Architecture

```
[API Server]
     |
     | (post created)
     v
[Kafka Producer] → Topic: post-events (partitioned by author_id)
                         |
              +----------+----------+
              |                     |
    [Fanout Worker 1]     [Fanout Worker 2]    (Consumer Group: feed-fanout-workers)
              |                     |
              v                     v
    [Redis Feed Sorted Sets]  [Redis Feed Sorted Sets]
                                    |
                                    v
                        [Popular User Registry] (Redis Set)
                                    |
                                    v (fanout-on-read at query time)
                        [Merge popular user posts into feed response]
```

---

## Hybrid Strategy Justification

**Fanout-on-write** for normal users: Post creation pushes post_id to every follower's Redis feed sorted set.

**Fanout-on-read** for popular users (100K+ followers): At feed query time, merge cached feed with recent posts from followed popular users.

**Why 100K threshold:**
- Below 100K: fanout-on-write completes in <10s with batched pipelining (1000 ZADDs/pipeline, 100 pipelines)
- Above 100K: latency and Redis load become significant (100K ZADD = 100 pipelines x 10ms = 1s per post)
- Users above 100K are typically <0.1% of user base — fanout-on-read merging is rare per request

---

## Kafka Topic Design

**Topic: `post-events`**
- **Partitions:** 12 (allows up to 12 parallel consumers)
- **Replication factor:** 3 (production durability standard)
- **Partition key:** `author_id` (preserves per-author ordering)
- **Retention:** 7 days (sufficient for consumer catch-up)

**Message schema:**
```json
{
    "event_type": "post_created" | "post_deleted",
    "post_id": "post_...",
    "author_id": "user_...",
    "timestamp": 1711929600.0,
    "follower_count": 542,
    "is_popular_user": false,
    "hashtags": ["reading", "bookclub"]
}
```

**Why `follower_count` in message:** Fanout worker decides write vs skip without Redis/DB lookup per message. Snapshotted at publish time — slight staleness acceptable given 100K threshold margin.

**DLQ:** `post-events-dlq` — messages failing after 3 retries. Monitoring/alerting watches DLQ depth.

---

## New Module Structure

```
events/
    __init__.py
    kafka_producer.py       # PostEventProducer singleton
    kafka_config.py         # Connection config, topic names

fanout_worker/
    __init__.py
    consumer.py             # Kafka consumer main loop
    fanout_service.py       # FanoutService: execute fanout-on-write
    popular_user_service.py # Popular user registry management
    fanout_worker.py        # Entry point (python fanout_worker.py)
```

**Modified files:**
- `posts/service/post_service.py` — publish Kafka event after post create/delete
- `follows/service/follow_service.py` — update popular user registry on follow/unfollow
- `shared/feed_cache.py` — add `get_feed_with_popular_merge()`
- `requirements-api.txt` — add `confluent-kafka>=2.3.0,<3`
- New: `requirements-fanout-worker.txt`, `Dockerfile.fanout-worker`

---

## Service Layer

### `events/kafka_producer.py`

```python
class PostEventProducer:
    def publish_post_created(self, post_id, author_id, timestamp, follower_count, hashtags) -> None:
        """Publish to post-events. Key=author_id. Fire-and-forget with delivery callback."""

    def publish_post_deleted(self, post_id, author_id, timestamp) -> None:
        """Publish post_deleted event."""
```

**Why confluent-kafka:** Project uses synchronous FastAPI handlers. confluent-kafka is the most performant Python client (librdkafka under the hood).

### `fanout_worker/fanout_service.py`

```python
class FanoutService:
    def handle_post_created(self, event: dict) -> None:
        """
        1. Check popular user registry → if popular: skip (fanout-on-read)
        2. Fetch follower IDs from PostgreSQL
        3. Batch ZADD to each follower's feed sorted set (pipeline batches of 500)
        4. Trim each set to MAX_FEED_SIZE
        """

    def handle_post_deleted(self, event: dict) -> None:
        """Fetch followers → batch ZREM from each feed."""
```

### `fanout_worker/popular_user_service.py`

```python
POPULAR_USER_KEY = "popular:users"
POPULAR_THRESHOLD = 100_000

class PopularUserService:
    def is_popular(self, user_id: str) -> bool:        # SISMEMBER
    def update_registry(self, user_id: str, count: int) -> None:  # SADD/SREM based on threshold
    def get_followed_popular_users(self, user_id: str, following_ids: list[str]) -> list[str]:
        """Intersection of following list with popular user set."""
```

### Feed merge at read time (extension to FeedCacheService)

```python
def get_feed_with_popular_merge(self, user_id, skip, limit, popular_user_ids, db):
    """
    1. Get cached feed page (fanout-on-write posts)
    2. For each followed popular user: query PG for their posts in same time window
    3. Heap merge both lists by timestamp
    4. Apply skip/limit to merged result
    """
```

**Why query PG for popular user posts at read time (not a separate Redis structure):** Popular users post at normal rates. Querying their last N posts from PG (index on `(author_id, created_at)`) is ~5ms per user. Typically 0-5 followed popular users per request = 0-25ms extra. Separate Redis structure adds complexity for minimal gain.

---

## Consumer Design

```python
def main():
    consumer = Consumer({
        'group.id': 'feed-fanout-workers',
        'auto.offset.reset': 'earliest',
        'enable.auto.commit': False,  # manual commit after processing
    })
    consumer.subscribe(['post-events'])
    # poll → dispatch → commit loop
```

**Manual commit:** Auto-commit risks marking consumed before processing completes. Manual commit after success guarantees at-least-once delivery. ZADD is idempotent (same score = no-op).

---

## Coexistence with Azure Queue

**Azure Queue Storage remains for PDF processing.** No reason to migrate — fundamentally different characteristics (low volume, large payloads, long processing). Kafka is for high-throughput social event fanout.

- Azure Queue: PDF processing (worker.py, mathpix_worker.py)
- Kafka: Social events (post-events, future: like-events, comment-events)

---

## Migration from Feed Cache (Task 2) to Kafka (Task 3)

Task 2 can deploy independently. In Task 2, `push_post_to_followers()` runs as a background thread. Task 3 replaces that thread with Kafka:

1. Deploy Task 2 with in-process background thread fanout
2. Deploy Kafka infrastructure and fanout worker
3. Replace `threading.Thread(target=push_to_followers)` with `PostEventProducer.publish_post_created()`
4. FeedCacheService methods remain identical — worker calls the same push methods

---

## Infrastructure

- **Kafka**: Azure Event Hubs (Kafka-compatible) or self-hosted
- **Fanout worker**: Docker container, Kubernetes Deployment with 3 replicas
- **Config**: `KAFKA_BROKERS`, `KAFKA_SECURITY_PROTOCOL`, `KAFKA_SASL_*`, `KAFKA_CONSUMER_GROUP`, `POPULAR_USER_THRESHOLD`
- **Monitoring**: Consumer lag per partition, DLQ depth, fanout latency

---

## Failure Handling

| Failure | Behavior |
|---------|----------|
| Kafka broker down | Producer buffers locally (librdkafka queue, 100K messages). create_post() logs error but completes. Feed falls back to SQL. |
| Worker crash | Consumer group rebalances. Another worker picks up partition. Duplicate ZADD is idempotent. |
| Redis down during fanout | Worker catches RedisError, publishes to retry topic. Feed falls back to SQL. |
| DLQ accumulation | Alert threshold: >100 messages. Manual investigation required. |

---

## Performance

- Fanout for 10K followers: 20 pipelines x 10ms = ~200ms per post event
- Popular user merge: 0-5 users x 5ms = 0-25ms negligible
- At 1000 posts/min with 12 partitions: ~83 msg/min per partition (trivial for Kafka)
- Worker memory: ~256MB containers (stateless)

---

## Critical Files

| File | Changes |
|------|---------|
| `events/kafka_producer.py` | New — PostEventProducer singleton |
| `events/kafka_config.py` | New — connection config, topic names |
| `fanout_worker/` | New — consumer, fanout service, popular user service |
| `posts/service/post_service.py` | Replace background thread with Kafka publish |
| `follows/service/follow_service.py` | Update popular user registry on follow/unfollow |
| `shared/feed_cache.py` | Add `get_feed_with_popular_merge()` |
| `requirements-api.txt` | Add `confluent-kafka>=2.3.0,<3` |

## Verification

Create post → verify Kafka message published → verify worker pushes to follower feeds. Create popular user (100K followers) post → verify no fanout-on-write → verify merge at read time.
