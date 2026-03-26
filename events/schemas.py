"""Pydantic models for all Kafka event payloads."""

from pydantic import BaseModel
from typing import Optional


# ── Social Events ────────────────────────────────────────────────────────────

class PostCreatedEvent(BaseModel):
    event_type: str = "post.created"
    post_id: str
    author_id: str
    user_text: Optional[str] = None
    content_text: Optional[str] = None
    doc_id: Optional[str] = None
    hashtags: list[str] = []
    timestamp: float
    follower_count: int = 0


class PostDeletedEvent(BaseModel):
    event_type: str = "post.deleted"
    post_id: str
    author_id: str
    timestamp: float


class PostLikedEvent(BaseModel):
    event_type: str = "post.liked"
    post_id: str
    actor_id: str
    author_id: str
    timestamp: float


class PostUnlikedEvent(BaseModel):
    event_type: str = "post.unliked"
    post_id: str
    actor_id: str
    author_id: str
    timestamp: float


class PostCommentedEvent(BaseModel):
    event_type: str = "post.commented"
    post_id: str
    comment_id: str
    actor_id: str
    author_id: str
    text_preview: str = ""
    timestamp: float


class PostCommentDeletedEvent(BaseModel):
    event_type: str = "post.comment_deleted"
    post_id: str
    comment_id: str
    actor_id: str
    timestamp: float


class PostResharedEvent(BaseModel):
    event_type: str = "post.reshared"
    post_id: str
    actor_id: str
    author_id: str
    timestamp: float


class PostReshareRemovedEvent(BaseModel):
    event_type: str = "post.reshare_removed"
    post_id: str
    actor_id: str
    author_id: str
    timestamp: float


class UserFollowedEvent(BaseModel):
    event_type: str = "user.followed"
    follower_id: str
    following_id: str
    follow_id: str
    timestamp: float
    new_follower_count: int = 0


class UserUnfollowedEvent(BaseModel):
    event_type: str = "user.unfollowed"
    follower_id: str
    following_id: str
    timestamp: float
    new_follower_count: int = 0


# ── AI Operations ────────────────────────────────────────────────────────────

class AskCompletedEvent(BaseModel):
    event_type: str = "ask.completed"
    user_id: str
    user_email: Optional[str] = None
    doc_id: str
    query: str = ""
    ai_response: str = ""
    node_costs: list[dict] = []
    rag_context: Optional[str] = None
    retrieval_chunks: list[dict] = []
    is_refusal: bool = False
    latency_ms: float = 0
    timestamp: float = 0


class AskStreamCompletedEvent(BaseModel):
    event_type: str = "ask.stream.completed"
    user_id: str
    user_email: Optional[str] = None
    doc_id: str
    query: str = ""
    ai_response: str = ""
    internal_state: dict = {}
    is_refusal: bool = False
    latency_ms: float = 0
    timestamp: float = 0


class ExplainWordCompletedEvent(BaseModel):
    event_type: str = "explain_word.completed"
    user_id: str
    user_email: Optional[str] = None
    doc_id: str
    word: str = ""
    content_id: Optional[int] = None
    page_id: Optional[int] = None
    ai_response: str = ""
    node_costs: list[dict] = []
    rag_context: Optional[str] = None
    is_refusal: bool = False
    latency_ms: float = 0
    timestamp: float = 0


class ExplainWordStreamCompletedEvent(BaseModel):
    event_type: str = "explain_word.stream.completed"
    user_id: str
    user_email: Optional[str] = None
    doc_id: str
    word: str = ""
    content_id: Optional[int] = None
    page_id: Optional[int] = None
    ai_response: str = ""
    internal_state: dict = {}
    is_refusal: bool = False
    latency_ms: float = 0
    timestamp: float = 0


# ── Document Events ──────────────────────────────────────────────────────────

class DocumentDisplayNameChangedEvent(BaseModel):
    event_type: str = "document.display_name_changed"
    doc_id: str
    old_name: str = ""
    new_name: str = ""
    timestamp: float = 0


class DocumentDeletedEvent(BaseModel):
    event_type: str = "document.deleted"
    doc_id: str
    owner_id: str
    og_doc_id: Optional[str] = None
    timestamp: float = 0


class DocumentAccessRequestedEvent(BaseModel):
    event_type: str = "document.access_requested"
    doc_id: str
    requester_id: str
    owner_id: str
    request_id: str
    document_display_name: str = ""
    timestamp: float = 0


# ── Billing Events ───────────────────────────────────────────────────────────

class BalanceCreditedEvent(BaseModel):
    event_type: str = "balance.credited"
    user_id: str
    amount_inr: float
    payment_id: str
    order_id: str
    razorpay_payment_id: str = ""
    balance_after: float = 0
    timestamp: float = 0


# ── Email Events ─────────────────────────────────────────────────────────────

class EmailVerificationEvent(BaseModel):
    event_type: str = "email.verification"
    user_id: str
    email: str
    verification_code: str
    timestamp: float = 0


class EmailPasswordResetEvent(BaseModel):
    event_type: str = "email.password_reset"
    email: str
    reset_code: str
    timestamp: float = 0


class EmailVerificationSuccessEvent(BaseModel):
    event_type: str = "email.verification_success"
    user_id: str
    email: str
    timestamp: float = 0
