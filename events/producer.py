"""Kafka producer singleton for publishing events from the API server."""

import json
import time
import logging
import threading

from events.config import _base_producer_config

logger = logging.getLogger(__name__)
from events.topics import (
    SOCIAL_EVENTS, AI_OPERATIONS, DOCUMENT_EVENTS,
    BILLING_EVENTS, EMAIL_EVENTS, partition_key_for_event,
)

_producer = None
_lock = threading.Lock()


def _delivery_callback(err, msg):
    if err:
        logger.error(f"[kafka-producer] Delivery failed for {msg.topic()}: {err}")
    else:
        logger.info(f"[kafka-producer] Delivered {msg.topic()}[{msg.partition()}] @offset {msg.offset()}")


def _get_producer():
    """Lazy-init the confluent-kafka Producer singleton."""
    global _producer
    if _producer is not None:
        return _producer
    with _lock:
        if _producer is not None:
            return _producer
        from confluent_kafka import Producer
        config = _base_producer_config()
        logger.info(f"[kafka-producer] Creating producer -> {config['bootstrap.servers']}")
        _producer = Producer(config)
        return _producer


def _publish(topic: str, event_type: str, payload: dict) -> None:
    """Serialize and publish an event. Fire-and-forget with delivery callback."""
    try:
        producer = _get_producer()
        payload["event_type"] = event_type
        if "timestamp" not in payload or not payload["timestamp"]:
            payload["timestamp"] = time.time()
        key = partition_key_for_event(event_type, payload)
        logger.info(f"[kafka-producer] Publishing {event_type} -> {topic} (key={key or 'None'})")
        producer.produce(
            topic=topic,
            key=key.encode("utf-8") if key else None,
            value=json.dumps(payload).encode("utf-8"),
            callback=_delivery_callback,
        )
        producer.flush(timeout=2.0)  # ensure message is delivered to broker
    except Exception as e:
        logger.error(f"[kafka-producer] Failed to publish {event_type}: {e}")


def flush_producer(timeout: float = 5.0) -> None:
    """Flush any buffered messages. Call during shutdown."""
    if _producer is not None:
        _producer.flush(timeout)


# ── Social Events ────────────────────────────────────────────────────────────

def publish_post_created(post_id: str, author_id: str, user_text: str = "",
                         content_text: str = "", doc_id: str = "",
                         hashtags: list[str] = None, follower_count: int = 0) -> None:
    _publish(SOCIAL_EVENTS, "post.created", {
        "post_id": post_id,
        "author_id": author_id,
        "user_text": user_text or "",
        "content_text": content_text or "",
        "doc_id": doc_id or "",
        "hashtags": hashtags or [],
        "follower_count": follower_count,
    })


def publish_post_deleted(post_id: str, author_id: str) -> None:
    _publish(SOCIAL_EVENTS, "post.deleted", {
        "post_id": post_id,
        "author_id": author_id,
    })


def publish_post_liked(post_id: str, actor_id: str, author_id: str) -> None:
    _publish(SOCIAL_EVENTS, "post.liked", {
        "post_id": post_id,
        "actor_id": actor_id,
        "author_id": author_id,
    })


def publish_post_unliked(post_id: str, actor_id: str, author_id: str) -> None:
    _publish(SOCIAL_EVENTS, "post.unliked", {
        "post_id": post_id,
        "actor_id": actor_id,
        "author_id": author_id,
    })


def publish_post_commented(post_id: str, comment_id: str, actor_id: str,
                           author_id: str, text_preview: str = "") -> None:
    _publish(SOCIAL_EVENTS, "post.commented", {
        "post_id": post_id,
        "comment_id": comment_id,
        "actor_id": actor_id,
        "author_id": author_id,
        "text_preview": text_preview[:200],
    })


def publish_post_comment_deleted(post_id: str, comment_id: str, actor_id: str) -> None:
    _publish(SOCIAL_EVENTS, "post.comment_deleted", {
        "post_id": post_id,
        "comment_id": comment_id,
        "actor_id": actor_id,
    })


def publish_post_reshared(post_id: str, actor_id: str, author_id: str) -> None:
    _publish(SOCIAL_EVENTS, "post.reshared", {
        "post_id": post_id,
        "actor_id": actor_id,
        "author_id": author_id,
    })


def publish_post_reshare_removed(post_id: str, actor_id: str, author_id: str) -> None:
    _publish(SOCIAL_EVENTS, "post.reshare_removed", {
        "post_id": post_id,
        "actor_id": actor_id,
        "author_id": author_id,
    })


def publish_user_followed(follower_id: str, following_id: str, follow_id: str,
                          new_follower_count: int = 0) -> None:
    _publish(SOCIAL_EVENTS, "user.followed", {
        "follower_id": follower_id,
        "following_id": following_id,
        "follow_id": follow_id,
        "new_follower_count": new_follower_count,
    })


def publish_user_unfollowed(follower_id: str, following_id: str,
                            new_follower_count: int = 0) -> None:
    _publish(SOCIAL_EVENTS, "user.unfollowed", {
        "follower_id": follower_id,
        "following_id": following_id,
        "new_follower_count": new_follower_count,
    })


# ── AI Operations ────────────────────────────────────────────────────────────

def publish_ask_completed(user_id: str, doc_id: str, result: dict,
                          latency_ms: float, user_email: str = None) -> None:
    _publish(AI_OPERATIONS, "ask.completed", {
        "user_id": user_id,
        "user_email": user_email,
        "doc_id": doc_id,
        "query": result.get("original_query", ""),
        "ai_response": result.get("ai_response", ""),
        "node_costs": result.get("node_costs", []),
        "rag_context": result.get("rag_context"),
        "retrieval_chunks": result.get("retrieval_chunks", []),
        "is_refusal": result.get("is_refusal", False),
        "latency_ms": latency_ms,
    })


def publish_ask_stream_completed(user_id: str, doc_id: str,
                                 ai_response: str, internal_state: dict,
                                 is_refusal: bool, latency_ms: float,
                                 user_email: str = None) -> None:
    _publish(AI_OPERATIONS, "ask.stream.completed", {
        "user_id": user_id,
        "user_email": user_email,
        "doc_id": doc_id,
        "query": internal_state.get("original_query", ""),
        "ai_response": ai_response,
        "internal_state": internal_state,
        "is_refusal": is_refusal,
        "latency_ms": latency_ms,
    })


def publish_explain_word_completed(user_id: str, doc_id: str, word: str,
                                   content_id: int = None, page_id: int = None,
                                   result: dict = None, ai_response: str = "",
                                   latency_ms: float = 0,
                                   user_email: str = None) -> None:
    result = result or {}
    _publish(AI_OPERATIONS, "explain_word.completed", {
        "user_id": user_id,
        "user_email": user_email,
        "doc_id": doc_id,
        "word": word,
        "content_id": content_id,
        "page_id": page_id,
        "ai_response": ai_response,
        "node_costs": result.get("node_costs", []),
        "rag_context": result.get("rag_context"),
        "is_refusal": result.get("is_refusal", False),
        "latency_ms": latency_ms,
    })


def publish_explain_word_stream_completed(user_id: str, doc_id: str, word: str,
                                          content_id: int = None, page_id: int = None,
                                          ai_response: str = "",
                                          internal_state: dict = None,
                                          latency_ms: float = 0,
                                          user_email: str = None) -> None:
    _publish(AI_OPERATIONS, "explain_word.stream.completed", {
        "user_id": user_id,
        "user_email": user_email,
        "doc_id": doc_id,
        "word": word,
        "content_id": content_id,
        "page_id": page_id,
        "ai_response": ai_response,
        "internal_state": internal_state or {},
        "is_refusal": (internal_state or {}).get("is_refusal", False),
        "latency_ms": latency_ms,
    })


# ── Document Events ──────────────────────────────────────────────────────────

def publish_document_display_name_changed(doc_id: str, old_name: str,
                                          new_name: str) -> None:
    _publish(DOCUMENT_EVENTS, "document.display_name_changed", {
        "doc_id": doc_id,
        "old_name": old_name,
        "new_name": new_name,
    })


def publish_document_deleted(doc_id: str, owner_id: str,
                             og_doc_id: str = None) -> None:
    _publish(DOCUMENT_EVENTS, "document.deleted", {
        "doc_id": doc_id,
        "owner_id": owner_id,
        "og_doc_id": og_doc_id,
    })


def publish_document_access_requested(doc_id: str, requester_id: str,
                                      owner_id: str, request_id: str,
                                      document_display_name: str = "") -> None:
    _publish(DOCUMENT_EVENTS, "document.access_requested", {
        "doc_id": doc_id,
        "requester_id": requester_id,
        "owner_id": owner_id,
        "request_id": request_id,
        "document_display_name": document_display_name,
    })


# ── Billing Events ───────────────────────────────────────────────────────────

def publish_balance_credited(user_id: str, amount_inr: float,
                             payment_id: str, order_id: str,
                             balance_after: float = 0) -> None:
    _publish(BILLING_EVENTS, "balance.credited", {
        "user_id": user_id,
        "amount_inr": amount_inr,
        "payment_id": payment_id,
        "order_id": order_id,
        "balance_after": balance_after,
    })


# ── Email Events ─────────────────────────────────────────────────────────────

def publish_email_verification(user_id: str, email: str,
                               verification_code: str) -> None:
    _publish(EMAIL_EVENTS, "email.verification", {
        "user_id": user_id,
        "email": email,
        "verification_code": verification_code,
    })


def publish_email_password_reset(email: str, reset_code: str) -> None:
    _publish(EMAIL_EVENTS, "email.password_reset", {
        "email": email,
        "reset_code": reset_code,
    })


def publish_email_verification_success(user_id: str, email: str) -> None:
    _publish(EMAIL_EVENTS, "email.verification_success", {
        "user_id": user_id,
        "email": email,
    })
