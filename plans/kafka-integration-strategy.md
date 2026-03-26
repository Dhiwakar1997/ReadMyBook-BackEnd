# Comprehensive Kafka Integration Strategy — ReadMyBook Backend

## Context

The ReadMyBook backend currently handles async work through 3 fragile mechanisms:

| Mechanism | Where | Problem |
|-----------|-------|---------|
| **`threading.Thread(daemon=True)`** | Eval recording, billing deduction, word explanation persistence, email sending, display name propagation | Silent failure on crash — eval/billing data permanently lost. No retry. No observability. |
| **Synchronous in-request writes** | Notifications (like, comment, reshare, access request) | Blocks the response path. If notification DB write is slow, user-facing latency increases. |

> **Note:** The PDF processing pipeline (worker_v2) stays on its current infrastructure and is **not** migrated to Kafka. It has different characteristics (low volume, CPU-bound, long-running) and is already working well.

**What Kafka solves:**
- **Guaranteed delivery** — messages persist on disk with configurable retention
- **Replay on failure** — consumers re-read from last committed offset after crash
- **Decoupling** — producers don't wait for consumers; consumers scale independently
- **Audit trail** — every event is an immutable log entry
- **Fan-out** — multiple consumer groups process the same event differently (notifications, analytics, cache invalidation)

---

## Codebase Async Operation Inventory

Every async operation found in the codebase, mapped to its proposed Kafka topic:

| # | Operation | Current Mechanism | Source File | Proposed Topic |
|---|-----------|-------------------|-------------|----------------|
| 1 | Ask eval recording | Background thread | `documents/service/document_service.py:188-230` | `ai-operations` |
| 2 | Ask stream eval recording | Background thread | `documents/service/document_service.py:307-366` | `ai-operations` |
| 3 | Ask billing deduction | Background thread (same as eval) | `documents/service/document_service.py:213-228` | `billing-events` |
| 4 | Explain word eval + persist | Background thread | `documents/service/document_service.py:393-465` | `ai-operations` |
| 5 | Explain word stream eval + persist | Background thread | `documents/service/document_service.py:531-602` | `ai-operations` |
| 6 | Explain word billing deduction | Background thread (same as eval) | `documents/service/document_service.py:435-458` | `billing-events` |
| 7 | Word explanation DB persistence | Background thread (same as eval) | `documents/service/document_service.py:443-459` | `ai-operations` |
| 8 | Display name propagation to posts | Background thread | `documents/service/document_service.py:121-131` | `document-events` |
| 9 | Verification email sending | Background thread | `users/service/user_service.py:265` | `email-events` |
| 10 | Password reset email sending | Background thread | `users/service/user_service.py:270` | `email-events` |
| 11 | Like notification | Synchronous `create_notification()` | `posts/service/post_service.py:188-195` | `social-events` |
| 12 | Comment notification | Synchronous `create_notification()` | `posts/service/post_service.py:220-227` | `social-events` |
| 13 | Reshare notification | Synchronous `create_notification()` | `posts/service/post_service.py:270-277` | `social-events` |
| 14 | Access request notification | Synchronous `create_notification()` | `documents/service/document_access_request_service.py:47-55` | `document-events` |
| 15 | Post creation (no fanout today) | Synchronous DB write only | `posts/service/post_service.py:78` | `social-events` |
| 16 | Post deletion (no fanout today) | Synchronous DB write only | `posts/service/post_service.py:87` | `social-events` |
| 17 | Follow/unfollow (no notification today) | Synchronous DB write only | `follows/service/follow_service.py:27,30` | `social-events` |
| 18 | Razorpay payment verified | Synchronous DB credit | `billing/route/billing_route.py:75-136` | `billing-events` |
| 19 | Cache invalidation (user/doc) | Synchronous Redis calls | `documents/service/document_service.py` various | `document-events` |

> **Excluded:** PDF pipeline (worker_v2), Mathpix fallback, and conversion billing — these stay on current worker_v2 infrastructure.

---

## Topic Architecture Overview

```
                            ┌──────────────────────────────────────────────┐
                            │              Kafka Cluster                    │
                            │                                              │
  API Server ──publish──►   │  ┌─────────────────┐   ┌─────────────────┐  │
                            │  │ social-events    │   │ ai-operations   │  │
                            │  │ (12 partitions)  │   │ (6 partitions)  │  │
                            │  └────────┬─────────┘   └────────┬────────┘  │
                            │           │                      │           │
                            │  ┌────────┴─────────┐   ┌───────┴────────┐  │
                            │  │ document-events   │   │ billing-events │  │
                            │  │ (6 partitions)    │   │ (6 partitions) │  │
                            │  └────────┬──────────┘   └───────┬────────┘  │
                            │           │                      │           │
                            │           │              ┌──────┴─────────┐ │
                            │           │              │ email-events   │ │
                            │           │              │ (3 partitions) │ │
                            │           │              └──────┬─────────┘ │
                            │           │                      │           │
                            │  ┌───────────────────────────────┘           │
                            │  │ DLQ topics (×5)    │                      │
                            │  │ (1 partition each) │                      │
                            │  └───────────────────┘                      │
                            └──────────────────────────────────────────────┘
                                         │
              ┌──────────────────────────┼──────────────────────────┐
              │                          │                          │
              ▼                          ▼                          ▼
     ┌─────────────────┐    ┌──────────────────────┐    ┌────────────────────┐
     │ Notification     │    │ Feed Fanout Worker   │    │ Analytics Worker   │
     │ Worker           │    │ (consumer group)     │    │ (consumer group)   │
     │ (consumer group) │    │                      │    │                    │
     └─────────────────┘    └──────────────────────┘    └────────────────────┘
```

---

## Topic 1: `social-events`

### Purpose
All user-to-user social interactions: post CRUD, likes, comments, reshares, follows. The backbone for feed fanout, notifications, and social analytics.

### Events

| Event Type | Trigger | Key | Payload |
|------------|---------|-----|---------|
| `post.created` | `PostService.create_post()` | `author_id` | `{post_id, author_id, user_text, content_text, doc_id, hashtags[], timestamp, follower_count}` |
| `post.deleted` | `PostService.delete_post()` | `author_id` | `{post_id, author_id, timestamp}` |
| `post.liked` | `PostService.like_post()` | `post_id` | `{post_id, actor_id, author_id, timestamp}` |
| `post.unliked` | `PostService.unlike_post()` | `post_id` | `{post_id, actor_id, author_id, timestamp}` |
| `post.commented` | `PostService.add_comment()` | `post_id` | `{post_id, comment_id, actor_id, author_id, text_preview, timestamp}` |
| `post.comment_deleted` | `PostService.delete_comment()` | `post_id` | `{post_id, comment_id, actor_id, timestamp}` |
| `post.reshared` | `PostService.reshare_post()` | `post_id` | `{post_id, actor_id, author_id, timestamp}` |
| `post.reshare_removed` | `PostService.unreshare_post()` | `post_id` | `{post_id, actor_id, author_id, timestamp}` |
| `user.followed` | `FollowService.follow_user()` | `following_id` | `{follower_id, following_id, follow_id, timestamp, new_follower_count}` |
| `user.unfollowed` | `FollowService.unfollow_user()` | `following_id` | `{follower_id, following_id, timestamp, new_follower_count}` |

### Partition Strategy

- **Partitions:** 12
- **Key logic:**
  - `post.created` / `post.deleted` → key = `author_id` (all posts by same author on same partition — preserves ordering for feed fanout)
  - `post.liked` / `post.commented` / `post.reshared` → key = `post_id` (all engagement on same post co-located — prevents race conditions in notification dedup)
  - `user.followed` / `user.unfollowed` → key = `following_id` (all follow events for a target user on same partition — accurate follower count tracking)

**Justification for 12 partitions:** Allows up to 12 parallel consumers in a consumer group. For a book-reading social platform, 12 partitions handle ~10K events/sec — 100x headroom over expected volume. Over-partitioning wastes broker resources; under-partitioning limits consumer parallelism.

### Consumer Groups

| Consumer Group | Consumes | Purpose |
|----------------|----------|---------|
| `feed-fanout-workers` | `post.created`, `post.deleted` | Push post_ids to follower feed caches (Redis ZSET) |
| `notification-workers` | `post.liked`, `post.commented`, `post.reshared`, `user.followed` | Create notification DB records + increment Redis unread counter |
| `social-analytics` | All events | Aggregate engagement metrics, trending posts, user activity scoring |
| `search-indexer` | `post.created`, `post.deleted` | Index/remove posts in Elasticsearch (replaces dual-write from Task 1) |
| `popular-user-tracker` | `user.followed`, `user.unfollowed` | Maintain popular user registry (Redis set) for hybrid fanout |

### DLQ
- **Topic:** `social-events-dlq` (1 partition)
- **Retry policy:** 3 attempts with exponential backoff (1s, 5s, 30s)
- **Alert threshold:** >50 messages in DLQ

---

## Topic 2: `ai-operations`

### Purpose
All AI/LLM operation completions: ask queries, word explanations, eval results. Decouples the hot path (returning response to user) from the cold path (eval, billing, persistence).

### Events

| Event Type | Trigger | Key | Payload |
|------------|---------|-----|---------|
| `ask.completed` | After `ask_the_rag()` returns | `user_id` | `{user_id, doc_id, query, ai_response, node_costs[], rag_context, retrieval_chunks[], is_refusal, latency_ms, timestamp}` |
| `ask.stream.completed` | After SSE stream finishes | `user_id` | `{user_id, doc_id, query, collected_tokens, internal_state, latency_ms, timestamp}` |
| `explain_word.completed` | After `getWordExplanation()` returns | `user_id` | `{user_id, doc_id, word, content_id, page_id, ai_explanation, node_costs[], is_refusal, latency_ms, timestamp}` |
| `explain_word.stream.completed` | After SSE stream finishes | `user_id` | `{user_id, doc_id, word, content_id, page_id, collected_tokens, internal_state, latency_ms, timestamp}` |

### Partition Strategy

- **Partitions:** 6
- **Key:** `user_id`

**Justification for user_id key:** Ensures all operations by one user land on the same partition. This means eval + billing for a single user are processed sequentially — prevents race conditions where two concurrent asks for the same user try to deduct balance simultaneously. 6 partitions are sufficient because AI operations are bounded by LLM latency (1-5s each), so throughput is naturally limited to ~100-500 ops/sec platform-wide.

### Consumer Groups

| Consumer Group | Consumes | Purpose |
|----------------|----------|---------|
| `eval-recording-workers` | All events | Run `eval_node()` → compute faithfulness, response_relevancy → write `EvalRecord` to DB |
| `billing-deduction-workers` | All events | Calculate total cost from `node_costs[]` → call `BalanceService.deduct_llm_cost()` |
| `word-explanation-persistence` | `explain_word.completed`, `explain_word.stream.completed` | Write `WordExplanation` record to DB |
| `ai-analytics` | All events | Track query patterns, refusal rates, latency distributions, cost trends |

**Why separate consumer groups for eval and billing (not one combined worker):** Currently these run in a single background thread. If eval_node() fails, billing is also skipped — a bug. Separate consumer groups ensure billing succeeds even if eval fails, and vice versa. Independent retry and DLQ per concern.

### DLQ
- **Topic:** `ai-operations-dlq` (1 partition)
- **Retry policy:** 5 attempts (eval can transiently fail on LLM rate limits)
- **Alert threshold:** >20 messages

### Message Size Consideration

These messages are the largest in the system (~5-50 KB due to `retrieval_chunks[]`, `collected_tokens`, `node_costs[]`). Kafka's default `max.message.bytes` is 1 MB — sufficient. For stream completions with very long responses, truncate `collected_tokens` to the final response text (not individual tokens) before publishing.

---

## Topic 3: `document-events`

### Purpose
Document lifecycle events: creation, updates, status transitions, sharing, deletion. Enables real-time frontend updates, cache invalidation, and cross-service coordination.

### Events

| Event Type | Trigger | Key | Payload |
|------------|---------|-----|---------|
| `document.created` | `DocumentService.create_document()` | `doc_id` | `{doc_id, owner_id, display_name, file_hash, timestamp}` |
| `document.updated` | `DocumentService.update_document()` | `doc_id` | `{doc_id, owner_id, changed_fields{}, timestamp}` |
| `document.display_name_changed` | `DocumentService.update_document()` | `doc_id` | `{doc_id, old_name, new_name, timestamp}` |
| `document.deleted` | `DocumentService.delete_document()` | `doc_id` | `{doc_id, owner_id, og_doc_id, timestamp}` |
| `document.status_changed` | Worker status transitions | `doc_id` | `{doc_id, old_status, new_status, timestamp}` |
| `document.processing_completed` | Worker final merge done | `doc_id` | `{doc_id, og_doc_id, category, sub_categories[], generated_title, summary, total_cost, timestamp}` |
| `document.processing_failed` | Worker 3x retry exhausted | `doc_id` | `{doc_id, reason, fallback_to_mathpix, timestamp}` |
| `document.shared` | `DocumentAccessService.share()` | `doc_id` | `{doc_id, owner_id, shared_with_user_id, timestamp}` |
| `document.unshared` | `DocumentAccessService.unshare()` | `doc_id` | `{doc_id, owner_id, removed_user_id, timestamp}` |
| `document.access_requested` | `DocumentAccessRequestService.create()` | `doc_id` | `{doc_id, requester_id, owner_id, request_id, timestamp}` |

### Partition Strategy

- **Partitions:** 6
- **Key:** `doc_id`

**Justification for doc_id key:** All events for the same document land on the same partition. This ensures ordering — a document can't be "completed" before it's "created", and display_name changes are applied in order. 6 partitions handle the expected document throughput (uploads are bounded by user action, not automated). Partition key on doc_id also means all sharing events for one document are sequential — prevents race conditions in access control cache updates.

### Consumer Groups

| Consumer Group | Consumes | Purpose |
|----------------|----------|---------|
| `cache-invalidation-workers` | `document.updated`, `document.deleted`, `document.shared`, `document.unshared` | Clear Redis caches (`clear_user_cache`, `clear_document_cache`, `invalidate_doc_meta`) |
| `display-name-propagation` | `document.display_name_changed` | Update `PostRepository.update_display_name_for_doc()` — replaces current background thread |
| `document-notification-workers` | `document.access_requested`, `document.shared` | Create notifications for document owners/recipients |
| `document-status-websocket` | `document.status_changed`, `document.processing_completed`, `document.processing_failed` | (Future) Push real-time status updates to frontend via WebSocket |
| `document-analytics` | All events | Track upload volume, conversion success rates, popular categories |

### DLQ
- **Topic:** `document-events-dlq` (1 partition)
- **Retry policy:** 3 attempts
- **Alert threshold:** >10 messages (document events are critical)

---

## Topic 4: `billing-events`

### Purpose
All financial transactions: balance credits (Razorpay), debits (LLM, conversion, Mathpix), and threshold alerts. Provides a complete financial audit trail and enables real-time balance monitoring.

### Events

| Event Type | Trigger | Key | Payload |
|------------|---------|-----|---------|
| `balance.credited` | Razorpay payment verified | `user_id` | `{user_id, amount_inr, payment_id, order_id, razorpay_payment_id, balance_after, timestamp}` |
| `balance.llm_deducted` | AI operation completed | `user_id` | `{user_id, raw_cost_usd, marked_up_cost_inr, operation (ask/explain_word/enrichment), document_id, token_count, balance_after, timestamp}` |
| `balance.conversion_deducted` | PDF conversion completed | `user_id` | `{user_id, total_seconds, cost_inr, document_id, balance_after, timestamp}` |
| `balance.mathpix_deducted` | Mathpix processing completed | `user_id` | `{user_id, pages, images, cost_inr, document_id, balance_after, timestamp}` |
| `balance.threshold_alert` | Balance falls below threshold | `user_id` | `{user_id, current_balance, threshold, last_operation, timestamp}` |
| `balance.exhausted` | Balance reaches zero | `user_id` | `{user_id, last_operation, document_id, timestamp}` |

### Partition Strategy

- **Partitions:** 6
- **Key:** `user_id`

**Justification for user_id key:** All financial events for one user on the same partition ensures sequential processing. This prevents a credit and debit for the same user being processed out of order by different consumers. 6 partitions are sufficient — billing events are bounded by user actions (at most ~10 events/sec per user during heavy usage).

**Why not doc_id:** A single LLM call may span multiple documents (future multi-doc ask). User_id is the natural entity for financial tracking.

### Consumer Groups

| Consumer Group | Consumes | Purpose |
|----------------|----------|---------|
| `billing-ledger-writer` | All events | Write to `BillingTransaction` table — the authoritative financial record. Currently this happens inline; moving to consumer guarantees delivery even if request crashes after deduction. |
| `balance-cache-updater` | All events | Update `billing:balance:{user_id}` in Redis. Currently done by `BalanceRepository` inline — moving to consumer decouples cache from write path. |
| `balance-alert-workers` | `balance.threshold_alert`, `balance.exhausted` | (Future) Send push notification or email when balance is low |
| `billing-analytics` | All events | Revenue dashboards, cost-per-user, LLM cost trends, conversion cost analysis |

### DLQ
- **Topic:** `billing-events-dlq` (1 partition)
- **Retry policy:** 5 attempts (financial data must not be lost)
- **Alert threshold:** >1 message (any billing DLQ entry is critical — trigger PagerDuty)

### Important: Billing Deduction Remains Synchronous in DB

The actual `BalanceRepository.deduct()` call stays as a synchronous DB write in the service layer (atomic, ACID). Only the **side effects** move to Kafka:
- Usage logging (`log_usage()`)
- Redis cache update
- Threshold alerts
- Analytics

This preserves the invariant that a user cannot overspend.

---

## Topic 5: `email-events`

### Purpose
All outbound email operations. Decouples email sending from the request path and provides retry on SMTP failures.

### Events

| Event Type | Trigger | Key | Payload |
|------------|---------|-----|---------|
| `email.verification` | User signup | `user_id` | `{user_id, email, verification_code, timestamp}` |
| `email.password_reset` | Password reset request | `email` | `{email, reset_code, timestamp}` |
| `email.verification_success` | Email verified | `user_id` | `{user_id, email, timestamp}` |
| `email.welcome` | (Future) First login after verify | `user_id` | `{user_id, email, first_name, timestamp}` |
| `email.balance_low` | (Future) Balance threshold | `user_id` | `{user_id, email, current_balance, timestamp}` |

### Partition Strategy

- **Partitions:** 3
- **Key:** `user_id` (or `email` for password reset where user_id may not be resolved)

**Justification for 3 partitions:** Email volume is low — signups + password resets + occasional alerts. 3 partitions provide minimal parallelism for burst handling (e.g., marketing email campaigns in future). Over-provisioning partitions wastes Kafka metadata overhead.

### Consumer Groups

| Consumer Group | Consumes | Purpose |
|----------------|----------|---------|
| `email-sender-workers` | All events | Call `EmailService.send_*()` methods. Replaces background threads in `user_service.py`. |

### DLQ
- **Topic:** `email-events-dlq` (1 partition)
- **Retry policy:** 5 attempts with exponential backoff (SMTP can be transiently down)
- **Alert threshold:** >20 messages

---

## Dead Letter Queue (DLQ) Strategy

Every topic has a corresponding DLQ topic with a consistent naming convention:

| Source Topic | DLQ Topic | Partitions | Retention |
|-------------|-----------|------------|-----------|
| `social-events` | `social-events-dlq` | 1 | 30 days |
| `ai-operations` | `ai-operations-dlq` | 1 | 30 days |
| `document-events` | `document-events-dlq` | 1 | 30 days |
| `billing-events` | `billing-events-dlq` | 1 | 90 days |
| `email-events` | `email-events-dlq` | 1 | 30 days |

**DLQ 1 partition justification:** DLQ messages are low-volume failure cases. A single partition keeps ordering for debugging. Multiple partitions would complicate manual replay.

**DLQ message format:**
```json
{
    "original_topic": "social-events",
    "original_partition": 3,
    "original_offset": 142857,
    "original_key": "user_abc123",
    "original_event": { ... },
    "error": "ConnectionRefusedError: Redis at 10.0.1.5:6379",
    "retry_count": 3,
    "first_failure_at": "2026-03-25T10:00:00Z",
    "last_failure_at": "2026-03-25T10:05:30Z",
    "consumer_group": "feed-fanout-workers",
    "consumer_id": "worker-2"
}
```

---

## Partition Summary

| Topic | Partitions | Key | Retention | Replication Factor |
|-------|-----------|-----|-----------|-------------------|
| `social-events` | 12 | `author_id` / `post_id` / `following_id` | 7 days | 3 |
| `ai-operations` | 6 | `user_id` | 3 days | 3 |
| `document-events` | 6 | `doc_id` | 7 days | 3 |
| `billing-events` | 6 | `user_id` | 90 days | 3 |
| `email-events` | 3 | `user_id` / `email` | 3 days | 3 |
| All DLQ topics | 1 each | original key | 30-90 days | 3 |

**Total partitions:** 12 + 6 + 6 + 6 + 3 + 5 = **38 partitions**

**Replication factor 3 justification:** Standard production durability. Tolerates 2 broker failures without data loss. Azure Event Hubs enforces this by default.

**Retention justification:**
- `billing-events` at 90 days — financial audit trail, can be replayed for reconciliation
- Most topics at 7 days — sufficient for consumer catch-up after multi-day outage
- `ai-operations` and `email-events` at 3 days — high-volume, low replay value after initial processing

---

## Infrastructure

### Azure Event Hubs (Recommended for Production)

- **Kafka-compatible API** — use `confluent-kafka` Python client with Event Hubs connection string
- **Pricing tier:** Standard (up to 40 consumer groups, 1000 partitions)
- **Throughput units:** Start with 2 TUs (2 MB/s ingress, 4 MB/s egress), auto-inflate to 10
- **Namespace:** `readmybook-events`

### Local Development

- Docker Compose with `confluentinc/cp-kafka:7.6.0` + KRaft mode (no Zookeeper)
- `KAFKA_BROKERS=localhost:9092` in `.env.dev`
- Single broker, replication factor 1

### Configuration

```env
# .env.dev
KAFKA_BROKERS=localhost:9092
KAFKA_SECURITY_PROTOCOL=PLAINTEXT

# .env.prod (Azure Event Hubs)
KAFKA_BROKERS=readmybook-events.servicebus.windows.net:9093
KAFKA_SECURITY_PROTOCOL=SASL_SSL
KAFKA_SASL_MECHANISM=PLAIN
KAFKA_SASL_USERNAME=$ConnectionString
KAFKA_SASL_PASSWORD=Endpoint=sb://readmybook-events.servicebus.windows.net/;SharedAccessKeyName=...
```

### New Dependencies

```
# requirements-api.txt
confluent-kafka>=2.3.0,<3

# requirements-worker.txt (existing, add)
confluent-kafka>=2.3.0,<3

# requirements-fanout-worker.txt (new)
confluent-kafka>=2.3.0,<3
redis>=7.0.0,<8
sqlalchemy>=2.0.0,<3
psycopg2-binary
```

---

## New Module Structure

```
events/
    __init__.py
    config.py               # Kafka connection config, topic names, serializer
    producer.py             # KafkaProducerService singleton (used by API + workers)
    consumer.py             # Base consumer class with DLQ, retry, offset management
    schemas.py              # Pydantic models for all event payloads
    topics.py               # Topic name constants + partition key resolvers

workers/
    notification_worker.py  # Consumes social-events → create_notification()
    eval_worker.py          # Consumes ai-operations → eval_node() + EvalRecord
    billing_worker.py       # Consumes ai-operations → deduct LLM costs
    email_worker.py         # Consumes email-events → EmailService.send_*()
    word_exp_worker.py      # Consumes ai-operations → WordExplanation persistence
    cache_worker.py         # Consumes document-events → Redis cache invalidation
    display_name_worker.py  # Consumes document-events → PostRepository update
```

---

## Migration Strategy

### Phase 1: Producer Infrastructure (Week 1)
- Add `events/` module with producer, config, schemas
- Publish events **alongside** existing mechanisms (dual-write)
- No consumers yet — messages accumulate in topics but no processing
- **Zero risk:** existing code paths unchanged

### Phase 2: Low-Risk Consumers (Week 2-3)
- Deploy `notification_worker.py` — consume `social-events` for notifications
- Deploy `email_worker.py` — consume `email-events` for email sending
- Deploy `display_name_worker.py` — consume `document-events` for name propagation
- Remove corresponding `threading.Thread` calls and inline `create_notification()` calls
- **Validation:** Compare notification counts before/after, email delivery rates

### Phase 3: AI Operations Consumers (Week 3-4)
- Deploy `eval_worker.py` — consume `ai-operations` for eval recording
- Deploy `billing_worker.py` — consume `ai-operations` for LLM cost deduction side-effects
- Deploy `word_exp_worker.py` — consume `ai-operations` for word explanation persistence
- Remove background threads from `document_service.py`
- **Validation:** Compare EvalRecord counts, billing transaction counts, word explanation counts

### Phase 4: Feed Fanout (Week 5+)
- Deploy feed fanout workers consuming `social-events` `post.created` / `post.deleted`
- This depends on the feed cache (Task 2) being deployed first
- See `kafka-fanout-architecture.md` for detailed fanout design

---

## Observability

### Key Metrics to Monitor

| Metric | Source | Alert Threshold |
|--------|--------|-----------------|
| Consumer lag (per group, per partition) | Kafka broker / Burrow | >1000 messages for >5 minutes |
| DLQ depth (per topic) | Kafka consumer on DLQ | >0 for billing, >50 for others |
| Producer publish latency (p99) | Client-side instrumentation | >500ms |
| Consumer processing latency (p99) | Client-side instrumentation | >5s for feed fanout, >10s for eval |
| End-to-end event latency | Timestamp in message vs processing time | >10s for notifications, >60s for billing |

### Logging

Every consumer logs:
```json
{
    "consumer_group": "notification-workers",
    "topic": "social-events",
    "partition": 3,
    "offset": 142857,
    "event_type": "post.liked",
    "processing_time_ms": 45,
    "status": "success"
}
```

---

## Cost Estimate (Azure Event Hubs)

| Component | Monthly Cost (Standard Tier) |
|-----------|------------------------------|
| 2 Throughput Units (base) | ~$44/month |
| Auto-inflate to 10 TUs (peak) | ~$220/month at peak |
| Ingress (estimated 10 GB/month) | ~$2.80/month |
| Storage (7-day retention, ~70 GB) | ~$7/month |
| **Total (typical)** | **~$55-80/month** |

Comparable self-hosted Kafka on Azure VMs would cost ~$150-300/month for a 3-node cluster.
