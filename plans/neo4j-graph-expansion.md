# Lean Hybrid Plan: Fix SQL Joins Without Expanding Neo4j

## Context

The codebase has 6 post-query methods in [posts/data/repository.py](posts/data/repository.py) that each build **3 count subqueries + 3 outer joins + 2 extra queries** for engagement data. At scale, these are the real bottleneck — not the graph. The fix is **denormalization + Redis**, not throwing more Neo4j at it.

**Budget**: Under $5K/mo total for graph + supporting infra.

**Strategy**: Keep Neo4j scoped to social graph only (Users + FOLLOWS — what it's already doing). Kill the expensive SQL joins via materialized counters on the Post table and Redis sets for user-specific engagement checks.

---

## Part 1: What Changes

### 1.1 Materialized Engagement Counters on Post Table (KILLS 3-subquery joins)

**Problem**: Every post read in [posts/data/repository.py](posts/data/repository.py) builds 3 subqueries:
```python
like_count_sq = self.db.query(Like.post_id, func.count(...)).group_by(...).subquery()
comment_count_sq = ...
reshare_count_sq = ...
# then 3 outer joins
```
This is repeated in `get_post_meta`, `get_my_posts`, `get_feed_posts`, `get_posts_by_ids`, `get_user_reshared_posts`, `get_reshared_posts` — 6 methods.

**Fix**: Add `like_count`, `comment_count`, `reshare_count` columns directly on the `Post` model. Update them atomically via Kafka consumers on the events that already exist.

**File**: [posts/data/model.py](posts/data/model.py)
```python
# Add to Post class
like_count = Column(Integer, default=0, nullable=False, server_default="0")
comment_count = Column(Integer, default=0, nullable=False, server_default="0")
reshare_count = Column(Integer, default=0, nullable=False, server_default="0")
```

**Migration SQL** (run once to backfill):
```sql
ALTER TABLE posts ADD COLUMN like_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE posts ADD COLUMN comment_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE posts ADD COLUMN reshare_count INTEGER NOT NULL DEFAULT 0;

UPDATE posts SET like_count = (SELECT COUNT(*) FROM likes WHERE likes.post_id = posts.post_id);
UPDATE posts SET comment_count = (SELECT COUNT(*) FROM comments WHERE comments.post_id = posts.post_id AND comments.is_deleted = false);
UPDATE posts SET reshare_count = (SELECT COUNT(*) FROM reshares WHERE reshares.post_id = posts.post_id);
```

**Kafka consumer updates** — new handler in event worker:

| Event (already published) | Action |
|---------------------------|--------|
| `post.liked` | `UPDATE posts SET like_count = like_count + 1 WHERE post_id = $1` |
| `post.unliked` | `UPDATE posts SET like_count = GREATEST(like_count - 1, 0) WHERE post_id = $1` |
| `post.commented` | `UPDATE posts SET comment_count = comment_count + 1 WHERE post_id = $1` |
| `post.comment.deleted` | `UPDATE posts SET comment_count = GREATEST(comment_count - 1, 0) WHERE post_id = $1` |
| `post.reshared` | `UPDATE posts SET reshare_count = reshare_count + 1 WHERE post_id = $1` |
| `post.reshare.removed` | `UPDATE posts SET reshare_count = GREATEST(reshare_count - 1, 0) WHERE post_id = $1` |

**Result**: All 6 repository methods drop the 3 subqueries and 3 outer joins. A post read becomes:
```python
self.db.query(Post, User)
    .join(User, User.user_id == Post.author_id)
    .filter(Post.post_id == post_id, Post.is_deleted == False)
    .first()
# like_count, comment_count, reshare_count are already on the Post object
```

### 1.2 Redis Sets for `is_liked_by_me` / `is_reshared_by_me` (KILLS 2 extra queries)

**Problem**: After fetching posts, every method does 2 more PG queries:
```python
liked_post_ids = set(self.db.query(Like.post_id).filter(Like.user_id == current_user_id, Like.post_id.in_(post_ids)).all())
reshared_post_ids = set(self.db.query(Reshare.post_id).filter(...).all())
```

**Fix**: Maintain Redis sets per user for liked and reshared post_ids.

**Redis keys**:
- `user:{user_id}:liked_posts` → Redis SET of post_ids
- `user:{user_id}:reshared_posts` → Redis SET of post_ids

**Updates via existing Kafka events**:
- `post.liked` → `SADD user:{actor_id}:liked_posts {post_id}`
- `post.unliked` → `SREM user:{actor_id}:liked_posts {post_id}`
- `post.reshared` → `SADD user:{actor_id}:reshared_posts {post_id}`
- `post.reshare.removed` → `SREM user:{actor_id}:reshared_posts {post_id}`

**Check**: `SISMEMBER user:{me}:liked_posts {post_id}` → O(1), replaces PG `IN()` query.

**Fallback**: If Redis key doesn't exist (cold user), backfill from PG on first access, then cache.

### 1.3 Fix the `following_ids` Feed Hot Path (TWO problems)

**Problem A — PG scan on every feed request**: [follows/data/repository.py:60-66](follows/data/repository.py#L60-L66) — `get_following_ids()` hits PG on every feed request, returning up to 5,000+ rows.

**Problem B — 5,000 Redis round-trips per feed request**: [popular_user_service.py:31-42](fanout_worker/popular_user_service.py#L31-L42) — `get_followed_popular_users(following_ids)` loops over the full list calling `SISMEMBER` per user_id. At 5,000 follows, that's **5,000 individual Redis calls on every single feed request**. This is the bigger bottleneck.

**Why caching the full following list in a Redis SET is not viable**:
- Each ULID user_id: ~25 bytes + Redis SET member overhead ~64 bytes = ~89 bytes/member
- 5,000 follows × 89 bytes = **435KB per user**
- At 100K power users that's **43GB of Redis RAM** just for follow lists
- Most of this data is cold — the user isn't online, but the key is still eating RAM

**Fix — Pipeline the SISMEMBER calls + keep PG as source of truth**:

The `following_ids` list is needed for two things:
1. Filter popular users from followed list → `get_followed_popular_users(following_ids)`
2. SQL fallback feed → `Post.author_id.IN(following_ids)` (cold cache only, rare)

**Solution for (1) — Redis pipeline instead of loop** (zero new storage):
```python
def get_followed_popular_users(self, following_ids: list[str]) -> list[str]:
    """Single Redis pipeline: 5000 SISMEMBER in 1 round-trip instead of 5000."""
    if not following_ids:
        return []
    pipe = self.redis.redis_client.pipeline(transaction=False)
    for uid in following_ids:
        pipe.sismember(POPULAR_USER_KEY, uid)
    results = pipe.execute()
    return [uid for uid, is_pop in zip(following_ids, results) if is_pop]
```
This turns 5,000 network round-trips into **1 pipelined batch**. ~2ms instead of ~500ms. No extra storage needed.

**Solution for (2) — PG hit is acceptable, it's the cold path**:
The SQL fallback (`get_feed_posts` with `Post.author_id.IN(following_ids)`) only fires when the Redis feed cache is empty — new user, Redis restart, or TTL expiry. This is rare. Hitting PG once for `get_following_ids()` on the cold path is fine.

For the cold path, optionally fall back to Neo4j instead of PG:
```cypher
MATCH (me:User {user_id: $user_id})-[:FOLLOWS]->(f)
RETURN collect(f.user_id) AS following_ids
```

**Net result**: No new Redis keys. No memory growth. The 5,000-call bottleneck becomes a single pipelined batch. PG remains the source of truth for follow lists.

### 1.4 Batch JOIN for Document Access Requests (KILLS N+1)

**Problem**: [document_access_request_service.py:63-81](documents/service/document_access_request_service.py#L63-L81) — `_enrich()` does N individual `get_user_by_id()` + `get_document_by_id()` calls.

**Fix**: Replace the loop with a single joined query:
```python
rows = (
    db.query(DocumentAccessRequest, User, Document)
    .join(User, User.user_id == DocumentAccessRequest.requester_id)
    .join(Document, Document.document_id == DocumentAccessRequest.document_id)
    .filter(DocumentAccessRequest.owner_id == user_id)
    .order_by(DocumentAccessRequest.created_at.desc())
    .all()
)
```
No Neo4j needed — just fix the query.

### 1.5 Neo4j Social Graph + PG Hydration for Recommendations (NEW)

**Pattern**: Use Neo4j for what it's good at (traversals), PG for data hydration.

**"Books popular in your network"**:
```python
# Step 1: Neo4j returns user_ids of friends (already exists)
friend_ids = graph_repo.get_friend_of_friend_recommendations(user_id)

# Step 2: PG query with indexed doc lookups
docs = db.query(Document, func.count(DocumentAccess.user_id))
    .join(DocumentAccess, ...)
    .filter(DocumentAccess.user_id.in_(friend_ids))
    .group_by(Document.document_id)
    .order_by(func.count(...).desc())
    .limit(20).all()
```

**"Social context on posts"** (e.g. "liked by 3 people you follow"):
```python
# Step 1: Get following_ids from Redis set (1.3 above)
following_ids = redis.smembers(f"following:{user_id}")

# Step 2: For displayed posts, check which following users liked them
# Small IN() query — only for the 20 posts on screen
likers = db.query(Like.post_id, Like.user_id)
    .filter(Like.post_id.in_(visible_post_ids), Like.user_id.in_(following_ids))
    .all()
```

---

## Part 2: Keep Neo4j Scoped (Current + Minor Additions)

Neo4j stays **exactly as-is** for social graph queries. No new node types.

| Feature | Already in Neo4j | Status |
|---------|-----------------|--------|
| Mutual followers | `get_mutual_followers()` | Done |
| Friend-of-friend recs | `get_friend_of_friend_recommendations()` | Done |
| Graph-ranked user search | `search_users()` | Done |
| Shortest path | `get_shortest_path()` | Done |
| Influence score | `get_influence_score()` | Done |

**One addition**: Add `get_following_ids()` to `graph_repository.py` as a Neo4j fallback when the Redis set from 1.3 is empty:
```cypher
MATCH (me:User {user_id: $user_id})-[:FOLLOWS]->(f)
RETURN collect(f.user_id) AS following_ids
```

---

## Part 3: Revised Architecture & Data Flow

```
                        ┌─────────────┐
                        │  Kafka Bus  │
                        └──────┬──────┘
                               │
         ┌─────────────────────┼─────────────────────────┐
         ▼                     ▼                          ▼
┌─────────────────┐  ┌─────────────────┐  ┌──────────────────────┐
│  Event Worker   │  │  Graph Sync     │  │  Fanout Worker       │
│  (counters +    │  │  Worker         │  │  (feed cache)        │
│   Redis sets)   │  │  (Neo4j edges)  │  │                      │
└────────┬────────┘  └────────┬────────┘  └──────────┬───────────┘
         │                    │                       │
         ▼                    ▼                       ▼
   ┌──────────┐        ┌──────────┐            ┌──────────┐
   │ Postgres │        │  Neo4j   │            │  Redis   │
   │ (data +  │        │ (social  │            │ (feeds + │
   │ counters)│        │  graph)  │            │  sets)   │
   └──────────┘        └──────────┘            └──────────┘

API Read Path:
1. Feed post_ids     ← Redis sorted set (fanout cache)
2. Post data+counts  ← PG (single join, counters on row)
3. is_liked/reshared ← Redis SISMEMBER (O(1) per post)
4. Recommendations   ← Neo4j traversal → PG hydration
```

---

## Part 4: Files to Modify

### Model changes
- [posts/data/model.py](posts/data/model.py) — add `like_count`, `comment_count`, `reshare_count` columns

### Repository changes (simplify all 6 methods)
- [posts/data/repository.py](posts/data/repository.py) — remove 3 subqueries + 3 outer joins from: `get_post_meta`, `get_my_posts`, `get_feed_posts`, `get_posts_by_ids`, `get_user_reshared_posts`, `get_reshared_posts`. Replace `is_liked`/`is_reshared` PG queries with Redis `SISMEMBER`.

### Service changes
- [documents/service/document_access_request_service.py](documents/service/document_access_request_service.py) — replace N+1 `_enrich()` with batch JOIN
- [fanout_worker/popular_user_service.py](fanout_worker/popular_user_service.py) — replace SISMEMBER loop with pipelined batch (5000 round-trips → 1)

### Event worker (new Kafka consumers)
- [event_worker.py](event_worker.py) or new handler module — consume `post.liked`/`post.unliked`/`post.commented`/`post.comment.deleted`/`post.reshared`/`post.reshare.removed` events to:
  1. Increment/decrement Post counter columns in PG
  2. SADD/SREM to `user:{id}:liked_posts` and `user:{id}:reshared_posts` Redis sets
- (no new consumer for following — fixed via pipelining in `PopularUserService`)

### Redis key additions
- `user:{user_id}:liked_posts` — SET of post_ids
- `user:{user_id}:reshared_posts` — SET of post_ids
- (no new keys for following — fixed via pipelining existing `popular:users` lookups)

### Neo4j (minor)
- [graph/data/graph_repository.py](graph/data/graph_repository.py) — add `get_following_ids()` as fallback

### Migration
- New: `migrations/add_post_counters.py` — ALTER TABLE + backfill

---

## Part 5: Revised Cost Estimation

### Under $5K/mo — Scales to 10M MAU

| Component | Spec | Monthly Cost |
|-----------|------|-------------|
| Neo4j (social graph only) | Single E8ds_v5 (8 vCPU, 64GB RAM) + 1 read replica | $1,200 |
| PostgreSQL | Already provisioned (add 3 integer columns, zero cost) | $0 |
| Redis | Already provisioned (sets add ~50MB per 1M users) | ~$0 |
| Kafka consumers | Code changes, runs on existing event worker | $0 |
| **Total new infra cost** | | **~$1,200/mo** |

### Growth Path

| MAU | Neo4j | PG | Redis (extra) | Total graph infra |
|-----|-------|----|---------------|-------------------|
| 100K | Single E4ds_v5 (4 vCPU, 32GB) | Existing | ~$0 | **$300/mo** |
| 1M | Single E8ds_v5 + 1 replica | Existing | ~$50 | **$1,250/mo** |
| 10M | 3-node E16ds_v5 cluster | Existing | ~$200 | **$3,600/mo** |
| 50M | 3-node E32ds_v5 + 2 replicas | Scale PG | ~$500 | **$8,000/mo** |
| 100M+ | Re-evaluate: add Post/Doc nodes to Neo4j | Shard PG | Cluster Redis | **$20K+/mo** |

### What This Buys You

| Query | Before (SQL) | After (Hybrid) | Speedup |
|-------|-------------|----------------|---------|
| `get_post_meta` | 3 subqueries + 3 outer joins + 2 extra queries | 1 simple JOIN + 3 Redis SISMEMBER | ~10-50x |
| `get_feed_posts` | 5 subqueries + 3 outer joins + 2 extra queries | Redis feed IDs → 1 JOIN → Redis checks | ~20-100x |
| `get_my_posts` | Same 3+3+2 pattern | 1 filtered JOIN | ~10-50x |
| `search_users` | 6 correlated subqueries (fallback) | Neo4j graph-ranked (already done) | ~100x |
| `_enrich` access requests | N+1 individual lookups | 1 batch JOIN | ~Nx |
| `get_followed_popular_users` | 5,000 individual SISMEMBER calls (~500ms) | 1 pipelined batch (~2ms) | ~250x |
| `get_following_ids` (feed) | PG scan every request | PG scan only on cold cache (rare) | N/A (architectural fix) |

---

## Part 6: Implementation Order

1. **Add counter columns to Post model + migration script** (unblocks everything)
2. **Add Kafka consumers for counter updates** (increment/decrement on events)
3. **Add Redis set consumers** (liked_posts, reshared_posts)
4. **Simplify all 6 PostRepository methods** (remove subqueries, use counters + Redis)
5. **Fix `_enrich()` N+1** (batch JOIN)
6. **Add `get_following_ids()` to graph_repository** (Neo4j fallback)
7. **Backfill migration** (populate counters from existing data, populate Redis sets)

---

## Part 7: Verification

1. Run `migrations/add_post_counters.py` locally, verify counts match `SELECT COUNT(*) FROM likes WHERE post_id = X`
2. Like/unlike a post via API → verify `post.like_count` increments/decrements in PG and post_id appears/disappears in Redis `user:{id}:liked_posts`
3. Load test `GET /feed` before/after with `k6`: measure p50/p99 latency improvement
4. Verify Redis fallback: flush a user's `liked_posts` key → confirm it backfills from PG on next request
5. Verify Neo4j circuit breaker still works: kill Neo4j → confirm user search falls back gracefully
6. Compare `EXPLAIN ANALYZE` of old vs new `get_feed_posts` query
