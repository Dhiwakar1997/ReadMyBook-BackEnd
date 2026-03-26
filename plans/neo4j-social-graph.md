# Graph Database for Social Relationships (Neo4j)

## Context

The ReadMyBook backend stores follow relationships in PostgreSQL. Queries like mutual followers, friend-of-friend recommendations, shortest path, and community detection require expensive N-hop JOINs in SQL that become prohibitive at scale. This plan introduces Neo4j as a graph database for relationship traversal queries while keeping PostgreSQL as the source of truth.

---

## Architecture

```
[API Server]
     |
     +→ [PostgreSQL]    (source of truth for follow CRUD)
     |       |
     |       +→ dual-write → [Neo4j]  (graph queries)
     |
     +→ [Neo4j]         (read-only for recommendations/discovery)
```

---

## Why Neo4j over ArangoDB

1. **Query language:** Cypher is the most mature graph query language. AQL is multi-model but less specialized for traversals.
2. **Ecosystem:** Largest community, best Python driver (`neo4j` package), mature managed hosting (Neo4j Aura on Azure Marketplace).
3. **Traversal performance:** Native graph storage with index-free adjacency. ArangoDB uses document store with graph layer — slower for 2+ hop traversals.
4. **Built-in graph algorithms:** Neo4j GDS library includes Louvain, Label Propagation, PageRank. ArangoDB requires external tools.
5. **Operational simplicity:** Neo4j Aura (managed) eliminates ops overhead.

**Counter-argument acknowledged:** ArangoDB is multi-model and could replace some PG use cases. But the project has well-established PG + Redis. A purpose-built graph DB for graph use cases is architecturally cleaner.

---

## Data Model (Neo4j)

**Node: User**
```cypher
(:User {
    user_id: "user_...",
    first_name: "John",
    last_name: "Doe",
    follower_count: 542,    -- denormalized, updated on follow/unfollow
    is_verified: true,
    is_private: false
})
```

**Edge: FOLLOWS**
```cypher
(:User)-[:FOLLOWS {
    created_at: datetime("2024-03-01T12:00:00Z"),
    id: "fw_..."    -- matches PG follows.id for traceability
}]->(:User)
```

**Indexes:**
```cypher
CREATE CONSTRAINT user_id_unique FOR (u:User) REQUIRE u.user_id IS UNIQUE;
CREATE INDEX user_follower_count FOR (u:User) ON (u.follower_count);
```

**Why denormalized `follower_count`:** Recommendation queries need to prioritize influential users. Without this, every query would count incoming FOLLOWS edges per candidate — expensive at scale.

---

## New Module Structure

```
graph/
    __init__.py
    data/
        neo4j_client.py          # Neo4j driver singleton
        graph_repository.py      # Cypher query execution
    service/
        graph_sync_service.py    # Dual-write sync logic
        recommendation_service.py # People you may know, mutual, community
    route/
        graph_route.py           # /graph/* endpoints
```

**Modified files:**
- `follows/service/follow_service.py` — add graph sync after PG write
- `app.py` — register graph_router
- `requirements-api.txt` — add `neo4j>=5.0.0,<6`

---

## Service Layer

### `graph/data/neo4j_client.py`

```python
from neo4j import GraphDatabase

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

def get_neo4j_session():
    return _driver.session()

def close_driver():
    _driver.close()
```

### `graph/data/graph_repository.py`

```python
class GraphRepository:
    def create_user_node(self, user_id, first_name, last_name, follower_count, is_verified) -> None:
        """MERGE (u:User {user_id: $user_id}) SET u.first_name = ..."""

    def create_follow_edge(self, follower_id, following_id, follow_id, created_at) -> None:
        """MATCH + MERGE edge. SET b.follower_count += 1"""

    def delete_follow_edge(self, follower_id, following_id) -> None:
        """MATCH + DELETE edge. SET b.follower_count -= 1"""

    def get_mutual_followers(self, user_a, user_b) -> list[dict]:
        """
        MATCH (a:User {user_id: $user_a})<-[:FOLLOWS]-(mutual)-[:FOLLOWS]->(b:User {user_id: $user_b})
        RETURN mutual.user_id, mutual.first_name, mutual.last_name
        """

    def get_friend_of_friend_recommendations(self, user_id, limit=20) -> list[dict]:
        """
        MATCH (me:User {user_id: $user_id})-[:FOLLOWS]->(friend)-[:FOLLOWS]->(rec)
        WHERE NOT (me)-[:FOLLOWS]->(rec)
          AND rec.user_id <> $user_id
          AND rec.is_private = false
        RETURN rec.user_id, rec.first_name, rec.last_name,
               rec.follower_count,
               COUNT(DISTINCT friend) AS mutual_count
        ORDER BY mutual_count DESC, rec.follower_count DESC
        LIMIT $limit
        """

    def get_shortest_path(self, user_a, user_b) -> list[dict]:
        """
        MATCH path = shortestPath(
            (a:User {user_id: $user_a})-[:FOLLOWS*..6]-(b:User {user_id: $user_b})
        )
        RETURN [n IN nodes(path) | n.user_id] AS user_ids,
               length(path) AS distance
        """

    def get_influence_score(self, user_id) -> dict:
        """
        MATCH (u:User {user_id: $user_id})
        OPTIONAL MATCH (u)<-[:FOLLOWS]-(follower)
        OPTIONAL MATCH (follower)<-[:FOLLOWS]-(second_degree)
        RETURN u.follower_count AS direct_followers,
               COUNT(DISTINCT second_degree) AS second_degree_reach
        """
```

### `graph/service/recommendation_service.py`

```python
class RecommendationService:
    def get_people_you_may_know(self, user_id, limit=20) -> list[dict]:
        """Redis cache (1h TTL) → graph_repo.get_friend_of_friend_recommendations()"""

    def get_mutual_followers(self, user_a, user_b) -> list[dict]:
        """Passthrough to graph_repo. PG fallback if Neo4j down."""

    def get_shortest_path(self, user_a, user_b) -> dict:
        """{user_ids: list, distance: int} or None. Max depth: 6."""

    def get_community_suggestions(self, user_id, limit=10) -> list[dict]:
        """Neo4j GDS Louvain algorithm. Cached 6 hours (heavy computation)."""
```

**Why cache recommendations:** 2-hop traversal for user following 500 people → 250K intermediate nodes. Neo4j handles it efficiently (~20ms), but 1-hour cache balances freshness with load.

---

## API Endpoints

```
GET /graph/recommendations?limit=20
  → [{user_id, first_name, last_name, mutual_count, follower_count}]

GET /graph/mutual-followers/{user_id}
  → [{user_id, first_name, last_name}]

GET /graph/shortest-path/{target_user_id}
  → {path: [user_ids], distance: int}

GET /graph/community-suggestions?limit=10
  → [{user_id, first_name, last_name, follower_count, community_id}]

GET /graph/influence/{user_id}
  → {user_id, direct_followers, second_degree_reach}
```

All endpoints require `verify_access_token`.

---

## Sync Strategy

**Dual-write from follow service (PG first, then Neo4j):**

```python
# In follows/service/follow_service.py
def follow_user(self, target_user_id):
    # ... existing PG logic ...
    self.follow_repository.create_follow(follow)

    # Graph sync (fire-and-forget)
    try:
        GraphRepository().create_follow_edge(
            follower_id=self.user_id,
            following_id=target_user_id,
            follow_id=follow.id,
            created_at=follow.created_at.isoformat()
        )
    except Exception as e:
        print(f"[graph_sync] Failed: {e}")
        # Queue for retry (graph_sync_failures table)
```

**Initial migration:** `migrations/populate_neo4j.py`
1. Load all users from PG → MERGE as User nodes
2. Load all follows from PG → MERGE as FOLLOWS edges
3. Compute follower_count per user → SET on node

**Consistency model:**
- PostgreSQL = source of truth for writes
- Neo4j = eventually-consistent read replica for graph queries
- Neo4j down → graph endpoints return 503, follow/unfollow works normally
- Nightly reconciliation job compares PG follow counts with Neo4j and fixes drift

---

## Failure Handling

| Failure | Behavior |
|---------|----------|
| Neo4j down during follow | PG write succeeds. Sync queued for retry. 200 returned to client. |
| Neo4j down during query | Graph endpoints return 503. |
| Neo4j slow | 3-second timeout → 503. |
| Data drift | Nightly reconciliation. Compare PG counts with Neo4j. |
| Neo4j lost/corrupted | Re-run populate_neo4j.py. Full rebuild in minutes for <1M users. |

**Mutual followers PG fallback:**
```sql
SELECT f1.follower_id FROM follows f1
JOIN follows f2 ON f1.follower_id = f2.follower_id
WHERE f1.following_id = :user_a AND f2.following_id = :user_b;
```

**No fallback for friend-of-friend or community detection** — prohibitively expensive in SQL. Return 503.

---

## Performance

- <1M users + <10M edges: single Neo4j instance (4GB RAM), all queries <100ms (dataset fits in memory)
- Friend-of-friend (avg_following=200): ~40K nodes traversed in ~20ms
- Shortest path (max depth 6): bidirectional BFS, <50ms
- Community detection (Louvain, 100K users): ~5-10s. Must be pre-computed and cached (6h TTL)
- Write throughput: ~10K txn/sec on commodity hardware (follow/unfollow at <100/sec is trivial)

---

## Rollout

- **Phase 1 (Week 1):** Deploy Neo4j. Run populate_neo4j.py. Deploy graph module endpoints (not exposed in frontend).
- **Phase 2 (Week 2):** Add dual-write in follow_service.py. Monitor consistency for 1 week. Deploy nightly reconciliation.
- **Phase 3 (Week 3):** Enable in frontend. Start with mutual followers + recommendations. Shortest path and community detection secondary.
- **Phase 4 (Week 4+):** Tune GDS. Add influence scoring to profiles. Consider pre-computing recommendations nightly.

---

## Critical Files

| File | Changes |
|------|---------|
| `graph/data/neo4j_client.py` | New — Neo4j driver singleton |
| `graph/data/graph_repository.py` | New — Cypher queries |
| `graph/service/recommendation_service.py` | New — recommendations, mutual, community |
| `graph/route/graph_route.py` | New — /graph/* endpoints |
| `follows/service/follow_service.py` | Add Neo4j dual-write on follow/unfollow |
| `app.py` | Register graph_router |
| `requirements-api.txt` | Add `neo4j>=5.0.0,<6` |
| `migrations/populate_neo4j.py` | New — one-time PG→Neo4j seed script |

## Verification

Follow user → verify Neo4j edge created. GET /graph/recommendations → verify 2-hop results. Kill Neo4j → verify 503 + mutual followers PG fallback.
