import datetime
from core.db_client import Base
from sqlalchemy import (
    Column, String, Boolean, DateTime, Text,
    ForeignKey, Integer, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import ARRAY


class Post(Base):
    __tablename__ = "posts"

    post_id = Column(String, primary_key=True, index=True, unique=True)
    author_id = Column(
        String,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_text = Column(Text, nullable=True)
    content_text = Column(Text, nullable=True)
    doc_id = Column(
        String,
        ForeignKey("documents.document_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    document_display_name = Column(String, nullable=True)
    content_ids = Column(ARRAY(Integer), nullable=True)
    page_numbers = Column(ARRAY(Integer), nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)


class Like(Base):
    __tablename__ = "likes"

    like_id = Column(String, primary_key=True, index=True, unique=True)
    user_id = Column(
        String,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    post_id = Column(
        String,
        ForeignKey("posts.post_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "post_id", name="uq_like_user_post"),
    )


class Comment(Base):
    __tablename__ = "comments"

    comment_id = Column(String, primary_key=True, index=True, unique=True)
    user_id = Column(
        String,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    post_id = Column(
        String,
        ForeignKey("posts.post_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)


class Reshare(Base):
    __tablename__ = "reshares"

    reshare_id = Column(String, primary_key=True, index=True, unique=True)
    user_id = Column(
        String,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    post_id = Column(
        String,
        ForeignKey("posts.post_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "post_id", name="uq_reshare_user_post"),
    )
