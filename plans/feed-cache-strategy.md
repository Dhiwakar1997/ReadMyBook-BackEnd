# Feed Cache Strategy

## Context

The ReadMyBook feed is computed on every request via SQL JOINs on the follows + posts tables (4 JOINs + 3 subqueries). This degrades as user/post count grows. This plan introduces a pre-computed Redis feed cache using sorted sets, with lazy warm-up and graceful SQL fallback.

---

## Architecture

```
Client → GET /posts/feed
           ↓
     [PostService.get_feed()]
           ↓
     [FeedCacheService]
       |                          |
   cache HIT                  cache MISS
       ↓                          ↓
  Redis ZREVRANGE          PostRepository.get_feed_posts()
  (sorted set → post_ids)   (original SQL query)
       ↓                          ↓
  PostRepository              FeedCacheService.warm_feed()
  .get_posts_by_ids()         (background thread)
       ↓                          ↓
  Enriched PostResponse      Return SQL results directly
```

---

## Data Model

No new PostgreSQL tables. Pure caching layer.

**Redis structures:**
```
Key:    feed:{user_id}
Type:   Sorted Set (ZSET)
Score:  Unix timestamp (float, from post.created_at)
Member: post_id (string)
TTL:    24 hours (refreshed on access)
Max:    1000 members (trimmed via ZREMRANGEBYRANK)

Key:    feed:{user_id}:warm
Type:   String ("1")
TTL:    5 minutes
Purpose: Debounce — prevents redundant warm-ups on concurrent cache misses
```

**Why sorted set:** ZSET is the canonical Redis feed structure. `ZREVRANGEBYSCORE` provides timestamp pagination. `ZADD` is O(log N). `ZRANGEBYSCORE` with LIMIT maps directly to skip/limit.

---

## New Files

```
shared/feed_cache.py    # FeedCacheService class (alongside shared/redis.py)
```

**Modified files:**
- `posts/service/post_service.py` — get_feed() calls FeedCacheService first
- `posts/data/repository.py` — add `get_posts_by_ids()` for batch enrichment
- `follows/service/follow_service.py` — invalidate feed cache on follow/unfollow

---

## Service Layer

### `shared/feed_cache.py`

```python
class FeedCacheService:
    FEED_KEY_PREFIX = "feed:"
    FEED_TTL = 86400         # 24 hours
    MAX_FEED_SIZE = 1000
    WARM_DEBOUNCE_TTL = 300  # 5 minutes

    def get_feed_page(self, user_id: str, skip: int, limit: int) -> tuple[list[str], bool]:
        """ZREVRANGE with start=skip, stop=skip+limit-1. Returns (post_ids, cache_hit)."""

    def warm_feed(self, user_id: str, post_id_timestamp_pairs: list[tuple[str, float]]) -> None:
        """Bulk ZADD + ZREMRANGEBYRANK to trim to MAX_FEED_SIZE. Sets TTL."""

    def push_post_to_followers(self, post_id: str, timestamp: float, follower_ids: list[str]) -> None:
        """ZADD to each follower's feed set via pipeline. Trims if over MAX_FEED_SIZE."""

    def remove_post_from_feeds(self, post_id: str, follower_ids: list[str]) -> None:
        """ZREM from each follower's feed for post deletion."""

    def invalidate_feed(self, user_id: str) -> None:
        """Delete feed key. Next access triggers full rebuild."""

    def get_feed_total(self, user_id: str) -> int:
        """ZCARD for pagination metadata."""

    def is_warming(self, user_id: str) -> bool:
        """Check debounce flag."""

    def set_warming(self, user_id: str) -> None:
        """Set debounce flag with TTL."""
```

### New method in `posts/data/repository.py`

```python
def get_posts_by_ids(self, post_ids: list[str], current_user_id: str) -> list[dict]:
    """Fetch posts with full metadata for a list of post_ids. Preserves input order."""
```

**Why preserve order:** Sorted set returns post_ids in correct timestamp order. SQL `WHERE IN (...)` doesn't guarantee order. Repository re-sorts via dict lookup: `{row.post_id: row}` then `[lookup[pid] for pid in post_ids if pid in lookup]`.

---

## Modified Feed Flow

**No changes to API contract.** `FeedResponse` schema remains identical. Pure backend optimization.

```python
def get_feed(self, skip, limit):
    cache = FeedCacheService()
    post_ids, hit = cache.get_feed_page(self.user_id, skip, limit)

    if hit and post_ids:
        total = cache.get_feed_total(self.user_id)
        rows = self.post_repo.get_posts_by_ids(post_ids, self.user_id)
        return FeedResponse(posts=[...], total=total, skip=skip, limit=limit)

    # Cache miss: fall back to SQL
    rows, total = self.post_repo.get_feed_posts(self.user_id, skip, limit)
    # Warm cache in background
    if not cache.is_warming(self.user_id):
        cache.set_warming(self.user_id)
        threading.Thread(target=self._warm_feed_cache, daemon=True).start()
    return FeedResponse(posts=[...], total=total, skip=skip, limit=limit)
```

---

## Cache Invalidation

| Event | Action |
|-------|--------|
| New post created | `push_post_to_followers()` — ZADD to all follower feeds (background thread) |
| Post deleted | `remove_post_from_feeds()` — ZREM from all follower feeds |
| User A follows B | `invalidate_feed(A)` — A's feed must include B's posts |
| User A unfollows B | `invalidate_feed(A)` — A's feed must exclude B's posts |

**Why full invalidation on follow/unfollow:** Surgically merging B's posts into A's sorted set is complex. Full invalidation is simpler. Follow/unfollow is rare (once per relationship change vs hundreds of feed reads).

---

## Capacity Planning

| Metric | Value |
|--------|-------|
| Per-user memory | ~40 KB (1000 members x ~40 bytes each) |
| 100K users | ~4 GB |
| 1M users | ~40 GB (requires Redis Cluster) |
| Current feed latency | ~50-200ms (SQL with 4 JOINs + 3 subqueries) |
| Cached feed latency | ~20-50ms (Redis ZREVRANGE + batch PG enrichment) |

---

## Failure Handling

- **Redis down**: `get_feed_page()` catches RedisError → returns ([], False) → falls through to SQL. Feed works exactly as today.
- **Redis slow**: 2-second timeout. Fallback to SQL.
- **Stale cache**: 24h TTL bounds staleness. Explicit invalidation on follow/unfollow handles most visible case.
- **Background thread failure**: `daemon=True` means thread dies silently. Next feed request triggers another warm-up attempt.

---

## Rollout

- **Phase 1 (Days 1-2):** Deploy FeedCacheService with `FEED_CACHE_ENABLED=false`. All code paths exist but bypassed.
- **Phase 2 (Days 3-4):** Enable for test user IDs. Monitor Redis memory, hit rate, response times.
- **Phase 3 (Day 5):** `FEED_CACHE_ENABLED=true`. Keep SQL fallback permanently.

---

## Critical Files

| File | Changes |
|------|---------|
| `shared/feed_cache.py` | New file — FeedCacheService |
| `posts/service/post_service.py` | get_feed() calls cache first, background warm-up |
| `posts/data/repository.py` | Add `get_posts_by_ids()` for batch enrichment |
| `follows/service/follow_service.py` | Invalidate feed cache on follow/unfollow |
| `shared/redis.py` | Add sorted set ops (ZADD, ZREVRANGE, ZREM, ZCARD, ZREMRANGEBYRANK) |

## Verification

GET /posts/feed → verify cache miss (SQL) → second request → verify cache hit (Redis). Follow new user → verify feed invalidation + rebuild.
