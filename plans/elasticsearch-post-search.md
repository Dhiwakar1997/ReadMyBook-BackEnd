# Elasticsearch Integration for Post Search

## Context

The ReadMyBook backend has no post search functionality. Users cannot search posts by text content or hashtags. No hashtag model exists. This plan introduces Elasticsearch for full-text post search with hashtag support, autocomplete, and trending.

---

## Architecture

```
Client → POST /search/posts
           ↓
     [FastAPI API Server]
       |                \
       v                 v
  [PostgreSQL]     [Elasticsearch 8.x]
  (source of truth)  (search index)
       |
       +--- sync-on-write --→ ES
```

**Strategy: Synchronous dual-write with async retry fallback.**

PostgreSQL remains the source of truth. On post create/delete, the service writes to PG first, then indexes in ES. If the ES write fails, the error is logged and a retry entry is queued to a `search_sync_failures` PostgreSQL table. A periodic background thread retries failed syncs.

**Why dual-write over CDC or outbox:**
- No Alembic, no Kafka, no Debezium currently — CDC would require significant new infrastructure
- Post creation volume is low (social posting, not high-frequency events)
- Matches existing patterns (notification system uses synchronous writes from service layer)
- Retry table handles the failure case that makes pure dual-write unreliable

---

## Data Model Changes

### New PostgreSQL Tables

**Hashtag + PostHashtag (in `posts/data/model.py`):**

```python
class Hashtag(Base):
    __tablename__ = "hashtags"
    hashtag_id = Column(String, primary_key=True, index=True)  # "ht_" + ULID
    tag = Column(String, nullable=False, unique=True, index=True)  # normalized lowercase, no '#'
    post_count = Column(Integer, default=0, nullable=False)  # denormalized for trending
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class PostHashtag(Base):
    __tablename__ = "post_hashtags"
    id = Column(Integer, primary_key=True, autoincrement=True)
    post_id = Column(String, ForeignKey("posts.post_id", ondelete="CASCADE"), nullable=False, index=True)
    hashtag_id = Column(String, ForeignKey("hashtags.hashtag_id", ondelete="CASCADE"), nullable=False, index=True)
    __table_args__ = (UniqueConstraint("post_id", "hashtag_id", name="uq_post_hashtag"),)
```

**SearchSyncFailure (in `search/data/model.py`):**

```python
class SearchSyncFailure(Base):
    __tablename__ = "search_sync_failures"
    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_type = Column(String, nullable=False)  # "post"
    entity_id = Column(String, nullable=False)     # post_id
    action = Column(String, nullable=False)        # "index" | "delete"
    payload = Column(Text, nullable=True)          # JSON snapshot
    retry_count = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    next_retry_at = Column(DateTime, default=datetime.datetime.utcnow)
```

**Why `post_count` on Hashtag:** Avoids `COUNT(*)` JOIN on `post_hashtags` for trending. Incremented/decremented atomically on post create/delete. Slight drift is acceptable — it's a display metric, not billing.

### Elasticsearch Index Mapping

```json
{
  "settings": {
    "number_of_shards": 1,
    "number_of_replicas": 1,
    "analysis": {
      "analyzer": {
        "post_text_analyzer": {
          "type": "custom",
          "tokenizer": "standard",
          "filter": ["lowercase", "asciifolding", "english_stop", "english_stemmer"]
        },
        "hashtag_autocomplete": {
          "type": "custom",
          "tokenizer": "keyword",
          "filter": ["lowercase", "edge_ngram_filter"]
        }
      },
      "filter": {
        "english_stop": { "type": "stop", "stopwords": "_english_" },
        "english_stemmer": { "type": "stemmer", "language": "english" },
        "edge_ngram_filter": { "type": "edge_ngram", "min_gram": 1, "max_gram": 20 }
      }
    }
  },
  "mappings": {
    "properties": {
      "post_id":               { "type": "keyword" },
      "author_id":             { "type": "keyword" },
      "user_text":             { "type": "text", "analyzer": "post_text_analyzer" },
      "content_text":          { "type": "text", "analyzer": "post_text_analyzer" },
      "combined_text":         { "type": "text", "analyzer": "post_text_analyzer" },
      "hashtags":              { "type": "keyword" },
      "hashtags_autocomplete": { "type": "text", "analyzer": "hashtag_autocomplete", "search_analyzer": "standard" },
      "document_display_name": { "type": "text", "analyzer": "post_text_analyzer" },
      "doc_id":                { "type": "keyword" },
      "created_at":            { "type": "date" },
      "is_deleted":            { "type": "boolean" }
    }
  }
}
```

**Mapping decisions:**
- `combined_text`: concatenation of user_text + content_text for single-field relevance scoring
- `hashtags` as `keyword`: enables exact-match filtering and terms aggregation for trending
- `hashtags_autocomplete` with edge_ngram: prefix matching separated from exact-match field
- Single shard: appropriate for expected volume (thousands to low millions of posts)
- `is_deleted` indexed: soft-deleted posts filtered without index removal (allows undelete)

---

## New Module Structure

```
search/
    __init__.py
    data/
        model.py              # SearchSyncFailure model
        schema.py             # SearchPostRequest, SearchPostResponse, HashtagAutocompleteResponse, TrendingHashtagsResponse
        repository.py         # SearchSyncFailureRepository
    service/
        elasticsearch_service.py   # ESService: index, delete, search, autocomplete, trending
        hashtag_service.py         # HashtagService: extract, create/link, get trending
        search_sync_service.py     # retry worker logic
    route/
        search_route.py       # /search/posts, /search/hashtags/autocomplete, /search/hashtags/trending
```

**Modified existing files:**
- `posts/data/model.py` — add Hashtag, PostHashtag models
- `posts/service/post_service.py` — call ES indexing and hashtag extraction on create/delete
- `app.py` — register search_router, import models, start retry thread in lifespan
- `requirements-api.txt` — add `elasticsearch>=8.0.0,<9`

---

## Service Layer Design

### `search/service/elasticsearch_service.py`

```python
class ESService:
    def __init__(self):
        self.client = elasticsearch_client  # module-level singleton

    def index_post(self, post: Post, hashtags: list[str]) -> bool:
        """Index or re-index a post. Returns True on success."""

    def delete_post(self, post_id: str) -> bool:
        """Mark post as deleted in ES (update is_deleted=True)."""

    def search_posts(self, query: str, hashtags: list[str] | None, skip: int, limit: int) -> tuple[list[str], int]:
        """Full-text search on combined_text + optional hashtag filter. Returns (post_ids, total_hits)."""

    def autocomplete_hashtags(self, prefix: str, limit: int = 10) -> list[dict]:
        """Edge-ngram prefix match. Returns [{tag, doc_count}]."""

    def get_trending_hashtags(self, hours: int = 24, limit: int = 20) -> list[dict]:
        """Terms aggregation on hashtags field, filtered by time. Returns [{tag, count}]."""
```

**Why search returns post_ids, not full data:** ES stores only searchable fields. Social metadata (like_count, is_liked_by_me, author info) must come from PostgreSQL. Search route calls `search_posts()` for IDs, then `PostRepository.get_posts_by_ids()` to enrich — same pattern as existing feed.

### `search/service/hashtag_service.py`

```python
class HashtagService:
    def __init__(self, db: Session):
        self.db = db

    def extract_hashtags(self, text: str) -> list[str]:
        """Regex: r'#([a-zA-Z0-9_]{1,50})' on user_text. Returns normalized lowercase tags."""

    def get_or_create_hashtags(self, tags: list[str]) -> list[Hashtag]:
        """Find existing or create. Increment post_count. Uses INSERT ON CONFLICT DO NOTHING."""

    def link_post_hashtags(self, post_id: str, hashtag_ids: list[str]) -> None:
        """Bulk insert into post_hashtags junction table."""

    def unlink_post_hashtags(self, post_id: str) -> None:
        """Delete all entries for a post. Decrement post_count on each hashtag."""
```

**Hashtag regex:** `r'#([a-zA-Z0-9_]{1,50})'` — industry standard (Twitter/X pattern). Max 50 chars prevents abuse. Only applied to `user_text` (not `content_text` which is book excerpts where # has no hashtag meaning).

---

## API Endpoints

```
POST   /search/posts
  Body: { "query": str, "hashtags": list[str]|null, "skip": int=0, "limit": int=20 }
  Response: { "posts": list[PostResponse], "total": int, "skip": int, "limit": int }
  Auth: verify_access_token

GET    /search/hashtags/autocomplete?prefix=str&limit=10
  Response: { "hashtags": list[{ "tag": str, "post_count": int }] }
  Auth: verify_access_token

GET    /search/hashtags/trending?hours=24&limit=20
  Response: { "hashtags": list[{ "tag": str, "count": int }] }
  Auth: verify_access_token
```

**Why POST for search:** Body can include complex filters (hashtag arrays, future: date ranges). POST for search is widely accepted (ES itself uses POST `_search`).

---

## Infrastructure

- **Elasticsearch 8.x**: Single-node dev, 3-node cluster prod
- **Hosting**: Azure Elastic Cloud (managed) or self-hosted Azure VM
- **Config**: `ELASTICSEARCH_URL`, `ELASTICSEARCH_API_KEY`, `ELASTICSEARCH_INDEX_PREFIX`
- **Connection**: Module-level singleton, mirroring `redis_client` pattern

---

## Sync/Consistency Strategy

1. **Write path**: PostService.create_post() → PG write → extract hashtags → link hashtags → index ES. If ES fails → log → insert SearchSyncFailure
2. **Delete path**: PostService.delete_post() → PG soft-delete → update is_deleted=True in ES. If ES fails → queue retry
3. **Retry worker**: Background thread in app.py lifespan. Polls search_sync_failures every 60s. Up to 5 retries with exponential backoff
4. **Consistency**: Eventual (up to 60s lag if ES temporarily down)
5. **Backfill**: One-time `migrations/backfill_elasticsearch.py` — reads all non-deleted posts, bulk-indexes

---

## Failure Handling

- **ES down**: Search endpoints return 503. Post CRUD continues normally (PG unaffected)
- **ES slow**: 5-second timeout. Treat as failure, queue retry
- **Autocomplete fallback**: `SELECT tag FROM hashtags WHERE tag LIKE 'prefix%' ORDER BY post_count DESC LIMIT 10`
- **Trending fallback**: `HashtagService.get_trending_from_db()`

---

## Rollout

- **Phase 1 (Week 1):** Add Hashtag + PostHashtag models. Deploy → create_all(). Extract hashtags on post creation. No ES yet. Zero-risk.
- **Phase 2 (Week 2):** Deploy ES infrastructure. Add ES client, indexing. Deploy search endpoints behind feature flag. Run backfill.
- **Phase 3 (Week 3):** Remove feature flag. Enable in frontend. Monitor cluster health, retry queue, latency.

---

## Critical Files

| File | Changes |
|------|---------|
| `posts/data/model.py` | Add Hashtag, PostHashtag models |
| `posts/service/post_service.py` | ES indexing + hashtag extraction on create/delete |
| `posts/data/repository.py` | Add `get_posts_by_ids()` for search result enrichment |
| `app.py` | Register search_router, import models, start retry thread |
| `requirements-api.txt` | Add `elasticsearch>=8.0.0,<9` |

## Verification

Create post with hashtags → search by text → verify results. Search by hashtag → verify filter. Kill ES → verify 503 + PG fallback for trending.
