# ── Topic names ──────────────────────────────────────────────────────────────

SOCIAL_EVENTS = "social-events"
AI_OPERATIONS = "ai-operations"
DOCUMENT_EVENTS = "document-events"
BILLING_EVENTS = "billing-events"
EMAIL_EVENTS = "email-events"

# DLQ topics
SOCIAL_EVENTS_DLQ = "social-events-dlq"
AI_OPERATIONS_DLQ = "ai-operations-dlq"
DOCUMENT_EVENTS_DLQ = "document-events-dlq"
BILLING_EVENTS_DLQ = "billing-events-dlq"
EMAIL_EVENTS_DLQ = "email-events-dlq"


def partition_key_for_event(event_type: str, payload: dict) -> str:
    """Determine the Kafka message key based on event type and payload.

    Key logic:
    - post.created / post.deleted -> author_id (feed fanout ordering)
    - post.liked / post.commented / post.reshared -> post_id (engagement co-location)
    - user.followed / user.unfollowed -> following_id (follower count tracking)
    - ai operations -> user_id
    - document events -> doc_id
    - billing events -> user_id
    - email events -> user_id or email
    """
    if event_type in ("post.created", "post.deleted"):
        return payload.get("author_id", "")
    if event_type in ("post.liked", "post.unliked", "post.commented",
                       "post.comment_deleted", "post.reshared", "post.reshare_removed"):
        return payload.get("post_id", "")
    if event_type in ("user.followed", "user.unfollowed"):
        return payload.get("following_id", "")
    if event_type.startswith("ask.") or event_type.startswith("explain_word."):
        return payload.get("user_id", "")
    if event_type.startswith("document."):
        return payload.get("doc_id", "")
    if event_type.startswith("balance."):
        return payload.get("user_id", "")
    if event_type.startswith("email."):
        return payload.get("user_id", payload.get("email", ""))
    return ""
