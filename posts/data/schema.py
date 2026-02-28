from pydantic import BaseModel, field_validator, model_validator
from datetime import datetime
from typing import Optional


# ── Request Schemas ──────────────────────────────────────────────────────────

class CreatePostRequest(BaseModel):
    user_text: Optional[str] = None
    content_text: Optional[str] = None
    doc_id: Optional[str] = None
    content_ids: Optional[list[int]] = None
    page_numbers: Optional[list[int]] = None

    @model_validator(mode="after")
    def at_least_one_text(self):
        if not (self.user_text and self.user_text.strip()) and not (self.content_text and self.content_text.strip()):
            raise ValueError("At least one of user_text or content_text must be provided")
        return self


class CreateCommentRequest(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def text_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Comment text cannot be empty")
        return v


# ── Sub-response Schemas ─────────────────────────────────────────────────────

class PostAuthorInfo(BaseModel):
    user_id: str
    first_name: str
    last_name: Optional[str] = None
    bio: Optional[str] = None

    class Config:
        from_attributes = True


class CommentResponse(BaseModel):
    comment_id: str
    user_id: str
    post_id: str
    text: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Post Response Schemas ────────────────────────────────────────────────────

class PostResponse(BaseModel):
    post_id: str
    author: PostAuthorInfo
    user_text: Optional[str] = None
    content_text: Optional[str] = None
    doc_id: Optional[str] = None
    document_display_name: Optional[str] = None
    content_ids: Optional[list[int]] = None
    page_numbers: Optional[list[int]] = None
    created_at: datetime
    like_count: int
    comment_count: int
    reshare_count: int
    is_liked_by_me: bool
    is_reshared_by_me: bool

    class Config:
        from_attributes = True


class FeedResponse(BaseModel):
    posts: list[PostResponse]
    total: int
    skip: int
    limit: int


class MyPostsResponse(BaseModel):
    posts: list[PostResponse]
    total: int
    skip: int
    limit: int


class ResharedPostsResponse(BaseModel):
    posts: list[PostResponse]
    total: int
    skip: int
    limit: int


class CommentListResponse(BaseModel):
    comments: list[CommentResponse]
    total: int
    skip: int
    limit: int


# ── Action Response Schemas ──────────────────────────────────────────────────

class PostActionResponse(BaseModel):
    message: str
    success: bool
    status_code: int


class LikeActionResponse(BaseModel):
    message: str
    success: bool
    status_code: int
    like_count: int


class ReshareActionResponse(BaseModel):
    message: str
    success: bool
    status_code: int
    reshare_count: int
