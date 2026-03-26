# Neo4j Relationship Graph — Implementation Plan

## Context

The ReadMyBook backend stores follow relationships in PostgreSQL. Graph queries (mutual followers, friend-of-friend recommendations, shortest path, influence scoring) require expensive multi-hop JOINs that become prohibitive at scale. This plan introduces Neo4j as an eventually-consistent graph read layer, synced via the existing Kafka event infrastructure, while PostgreSQL remains the source of truth.

The existing design doc at `plans/neo4j-social-graph.md` covers the data model, Cypher queries, API endpoints, and failure semantics. This plan focuses on **implementation order, Azure provisioning, and one key architectural change** — replacing the proposed dual-write with an event-driven sync worker.

---

## Key Architectural Decision: Event-Driven Sync (not Dual-Write)

The original plan proposes dual-write in `follow_service.py`. Instead, use a **new `graph_sync_worker`** consuming from the existing `social-events` Kafka topic.

**Why:**
- Every other side-effect in the codebase (feed fanout, notifications, eval, billing, cache invalidation, email) is event-driven via Kafka workers extending `BaseConsumer`
- `user.followed` / `user.unfollowed` events already contain all needed fields (`follower_id`, `following_id`, `follow_id`, `new_follower_count`)
- Zero added latency to follow/unfollow endpoints
- API server has no Neo4j dependency for writes — only for read endpoints
- Gets DLQ + retry (3x exponential backoff) for free via `BaseConsumer`
- `follow_service.py` stays unchanged

**Trade-off:** ~1 second sync delay (Kafka latency). Acceptable — the plan already defines Neo4j as eventually-consistent.

**User node data:** Events don't carry user names/verification. The worker queries PG for user details (same pattern as `fanout_worker` looking up follower lists). MERGE with just `user_id` if PG lookup fails; reconciliation fills gaps later.

---

## Azure Resource Provisioning

### Recommended: Azure Container Instance (ACI)

For <1M users / <10M edges, a single 4GB Neo4j instance is sufficient. ACI is the lowest-cost, lowest-ops option (~$30-50/month). Migrate to Container Apps or Neo4j Aura when production load warrants it.

### Azure CLI Commands

```bash
# ── Variables ──────────────────────────────────────────────────────────────
RG="your-resource-group"
LOCATION="centralindia"
STORAGE_ACCOUNT="readmybookneo4j"
FILE_SHARE_NAME="neo4j-data"
CONTAINER_NAME="readmybook-neo4j"
NEO4J_PASSWORD="<generate-strong-password>"
KV_NAME="your-keyvault-name"

# ── 1. Storage account + file share for Neo4j persistence ─────────────────
az storage account create \
  --resource-group $RG \
  --name $STORAGE_ACCOUNT \
  --location $LOCATION \
  --sku Standard_LRS \
  --kind StorageV2

STORAGE_KEY=$(az storage account keys list \
  --resource-group $RG \
  --account-name $STORAGE_ACCOUNT \
  --query "[0].value" -o tsv)

az storage share create \
  --account-name $STORAGE_ACCOUNT \
  --account-key $STORAGE_KEY \
  --name $FILE_SHARE_NAME \
  --quota 10

# ── 2. Neo4j container instance ───────────────────────────────────────────
az container create \
  --resource-group $RG \
  --name $CONTAINER_NAME \
  --image neo4j:5-community \
  --cpu 2 \
  --memory 4 \
  --ports 7474 7687 \
  --ip-address Public \
  --os-type Linux \
  --environment-variables \
    NEO4J_AUTH="neo4j/$NEO4J_PASSWORD" \
    NEO4J_server_memory_heap_initial__size="1g" \
    NEO4J_server_memory_heap_max__size="2g" \
    NEO4J_server_memory_pagecache_size="512m" \
  --azure-file-volume-account-name $STORAGE_ACCOUNT \
  --azure-file-volume-account-key $STORAGE_KEY \
  --azure-file-volume-share-name $FILE_SHARE_NAME \
  --azure-file-volume-mount-path /data \
  --restart-policy Always

# ── 3. Get public IP for bolt:// URI ──────────────────────────────────────
NEO4J_IP=$(az container show \
  --resource-group $RG \
  --name $CONTAINER_NAME \
  --query "ipAddress.ip" -o tsv)

echo "NEO4J_URI=bolt://${NEO4J_IP}:7687"

# ── 4. Store credentials in Key Vault ─────────────────────────────────────
az keyvault secret set --vault-name $KV_NAME --name "NEO4J-URI" \
  --value "bolt://${NEO4J_IP}:7687"
az keyvault secret set --vault-name $KV_NAME --name "NEO4J-USER" \
  --value "neo4j"
az keyvault secret set --vault-name $KV_NAME --name "NEO4J-PASSWORD" \
  --value "$NEO4J_PASSWORD"

# ── 5. (Production) VNET-integrated deployment for private networking ─────
# Replace step 2 with:
# az container create ... \
#   --vnet $VNET_NAME \
#   --subnet $SUBNET_NAME \
#   --ip-address Private \
#   (remove --ip-address Public)
```

### Graph Sync Worker Container (after code is ready)

```bash
# Build and push worker image
az acr build --registry $ACR_NAME \
  --image graph-sync-worker:latest \
  --file Dockerfile.graph-sync-worker .

# Deploy as ACI (or add to existing container orchestration)
az container create \
  --resource-group $RG \
  --name readmybook-graph-sync-worker \
  --image "${ACR_NAME}.azurecr.io/graph-sync-worker:latest" \
  --cpu 1 \
  --memory 1 \
  --ip-address None \
  --os-type Linux \
  --environment-variables \
    NEO4J_URI="bolt://${NEO4J_IP}:7687" \
    NEO4J_USER="neo4j" \
    NEO4J_PASSWORD="$NEO4J_PASSWORD" \
    KAFKA_BOOTSTRAP_SERVERS="$KAFKA_SERVERS" \
    DATABASE_URL="$PG_CONNECTION_STRING" \
  --restart-policy Always
```

---

## Implementation Phases

### Phase 1: Infrastructure + Core Module (Day 1-2)

| # | File | Action | Details |
|---|------|--------|---------|
| 1 | `docker-compose.neo4j.yml` | NEW | Neo4j 5 Community, ports 7474/7687, health check, named volumes |
| 2 | `.env.dev` | MODIFY | Add `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` |
| 3 | `graph/__init__.py` | NEW | Empty |
| 4 | `graph/data/__init__.py` | NEW | Empty |
| 5 | `graph/data/neo4j_client.py` | NEW | Driver singleton (pattern: `shared/redis.py`). Env vars: `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`. Pool: `max_connection_pool_size=25`, `connection_acquisition_timeout=5`. Graceful None if not configured. |
| 6 | `graph/data/graph_repository.py` | NEW | All Cypher queries: `ensure_constraints()`, `merge_user_node()`, `create_follow_edge()`, `delete_follow_edge()`, `get_mutual_followers()`, `get_friend_of_friend_recommendations()`, `get_shortest_path()`, `get_influence_score()`. 3s query timeout. |
| 7 | `graph/data/schema.py` | NEW | Pydantic models: `RecommendationUser`, `RecommendationsResponse`, `ShortestPathResponse`, `InfluenceResponse` |
| 8 | `requirements-api.txt` | MODIFY | Add `neo4j>=5.0.0,<6` |

### Phase 2: Sync Worker + Migration (Day 3-4)

| # | File | Action | Details |
|---|------|--------|---------|
| 9 | `events/config.py` | MODIFY | Add `CONSUMER_GROUP_GRAPH_SYNC = "graph-sync-workers"` |
| 10 | `workers/graph_sync_worker.py` | NEW | Extends `BaseConsumer`, subscribes to `SOCIAL_EVENTS`, handles `user.followed` / `user.unfollowed`. Queries PG for user details via `UserRepository`. |
| 11 | `requirements-graph-sync-worker.txt` | NEW | `confluent-kafka`, `neo4j`, `redis`, `SQLAlchemy`, `psycopg2-binary`, `python-dotenv` |
| 12 | `migrations/populate_neo4j.py` | NEW | Batch MERGE users (500/txn via UNWIND), batch MERGE edges, compute `follower_count`. Idempotent. |

**Test:** `docker compose -f docker-compose.neo4j.yml up -d` → `python -m migrations.populate_neo4j` → verify in Neo4j browser at `localhost:7474`

### Phase 3: API Endpoints (Day 5-6)

| # | File | Action | Details |
|---|------|--------|---------|
| 13 | `graph/service/__init__.py` | NEW | Empty |
| 14 | `graph/service/recommendation_service.py` | NEW | Redis-cached recommendations (1h TTL, key `graph:recs:{user_id}`). Mutual followers with PG fallback. Shortest path + influence (Neo4j only, 503 on failure). Simple circuit breaker (5 consecutive failures → 30s cooldown). |
| 15 | `graph/route/__init__.py` | NEW | Export `graph_router` |
| 16 | `graph/route/graph_route.py` | NEW | `GET /graph/recommendations`, `/mutual-followers/{user_id}`, `/shortest-path/{target_user_id}`, `/influence/{user_id}`, `/health`. All require `verify_access_token`. |
| 17 | `app.py` | MODIFY | Register `graph_router`, add `close_driver()` to lifespan shutdown |

### Phase 4: Production Hardening (Day 7+)

| # | File | Action | Details |
|---|------|--------|---------|
| 18 | `migrations/reconcile_neo4j.py` | NEW | Nightly script: compare PG/Neo4j follower counts, fix drift, remove orphaned edges, create missing edges |
| 19 | `Dockerfile.graph-sync-worker` | NEW | Same pattern as existing worker Dockerfiles |

---

## Neo4j Data Model (from design doc)

```cypher
-- Node
(:User {user_id, first_name, last_name, follower_count, is_verified, is_private})

-- Edge
(:User)-[:FOLLOWS {id, created_at}]->(:User)

-- Constraints
CREATE CONSTRAINT user_id_unique FOR (u:User) REQUIRE u.user_id IS UNIQUE;
CREATE INDEX user_follower_count FOR (u:User) ON (u.follower_count);
```

---

## Redis Cache Keys (new)

| Key | TTL | Purpose |
|-----|-----|---------|
| `graph:recs:{user_id}` | 1h | Friend-of-friend recommendations |
| `graph:influence:{user_id}` | 1h | Influence score |

---

## Verification

1. **Local:** `docker compose -f docker-compose.neo4j.yml up -d` → run `populate_neo4j.py` → open `localhost:7474` → verify nodes/edges
2. **Sync:** Start `graph_sync_worker` → follow a user via API → verify new edge appears in Neo4j within ~1s
3. **Endpoints:** `GET /graph/recommendations` returns 2-hop results → `GET /graph/mutual-followers/{id}` returns shared followers
4. **Resilience:** Stop Neo4j container → verify follow/unfollow still works (PG only) → graph endpoints return 503 → mutual followers falls back to PG SQL → restart Neo4j → worker replays queued events

---

## Known Limitations

- **Community detection skipped initially:** Neo4j Community Edition does not include the GDS library needed for Louvain. The `/community-suggestions` endpoint from the design doc is deferred until GDS licensing is resolved.
- **No `follow_service.py` changes needed:** The event-driven approach means the follow service stays untouched — a departure from the original design doc.
