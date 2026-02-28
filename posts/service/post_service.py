import ulid
import datetime

from fastapi import Request, HTTPException
from sqlalchemy.orm import Session

from posts.data.model import Post, Like, Comment, Reshare
from posts.data.repository import (
    PostRepository, LikeRepository, CommentRepository, ReshareRepository
)
from notifications.service.notification_service import create_notification
from documents.data.repository import DocumentRepository
from posts.data.schema import (
    CreatePostRequest, CreateCommentRequest,
    PostResponse, PostAuthorInfo, FeedResponse, MyPostsResponse,
    ResharedPostsResponse, CommentListResponse, CommentResponse,
)


def _build_post_response(row: dict) -> PostResponse:
    post: Post = row["post"]
    author = row["author"]
    return PostResponse(
        post_id=post.post_id,
        author=PostAuthorInfo(
            user_id=author.user_id,
            first_name=author.first_name,
            last_name=author.last_name,
            bio=getattr(author, "bio", None),
        ),
        user_text=post.user_text,
        content_text=post.content_text,
        doc_id=post.doc_id,
        document_display_name=post.document_display_name,
        content_ids=post.content_ids,
        page_numbers=post.page_numbers,
        created_at=post.created_at,
        like_count=row["like_count"],
        comment_count=row["comment_count"],
        reshare_count=row["reshare_count"],
        is_liked_by_me=row["is_liked_by_me"],
        is_reshared_by_me=row["is_reshared_by_me"],
    )


class PostService:
    def __init__(self, db: Session, request: Request):
        self.db = db
        self.request = request
        self.post_repo = PostRepository(db)
        self.like_repo = LikeRepository(db)
        self.comment_repo = CommentRepository(db)
        self.reshare_repo = ReshareRepository(db)
        self.document_repo = DocumentRepository(db)
        self.user_id = request.state.user_id

    # ── Post Operations ───────────────────────────────────────────────────────

    def create_post(self, payload: CreatePostRequest) -> Post:
        display_name = None
        if payload.doc_id:
            doc = self.document_repo.get_document_by_id(payload.doc_id)
            if doc:
                display_name = doc.display_name

        post = Post(
            post_id="post_" + str(ulid.new()),
            author_id=self.user_id,
            user_text=payload.user_text,
            content_text=payload.content_text,
            doc_id=payload.doc_id,
            document_display_name=display_name,
            content_ids=payload.content_ids,
            page_numbers=payload.page_numbers,
            created_at=datetime.datetime.utcnow(),
            updated_at=datetime.datetime.utcnow(),
        )
        return self.post_repo.create_post(post)

    def delete_post(self, post_id: str) -> bool:
        post = self.post_repo.get_post_by_id(post_id)
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        if post.author_id != self.user_id:
            raise HTTPException(status_code=403, detail="Not authorised to delete this post")
        return self.post_repo.delete_post(post)

    # ── My Posts ──────────────────────────────────────────────────────────────

    def get_my_posts(self, skip: int = 0, limit: int = 20) -> MyPostsResponse:
        rows, total = self.post_repo.get_my_posts(self.user_id, skip=skip, limit=limit)
        posts = [_build_post_response(row) for row in rows]
        return MyPostsResponse(posts=posts, total=total, skip=skip, limit=limit)

    def _check_user_privacy(self, target_user_id: str):
        """Raise 403 if the target user's account is private."""
        from shared.redis import RedisService
        from middleware import _user_context_key, USER_CONTEXT_CACHE_TTL

        redis = RedisService()
        target_ctx = redis.get_value(_user_context_key(target_user_id))

        if target_ctx is None:
            from users.data.repository import UserRepository
            from billing.data.repository import BalanceRepository

            user = UserRepository(self.db).get_user_by_id(target_user_id)
            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            balance = BalanceRepository(self.db).get_balance(target_user_id)
            target_ctx = {
                "user_id": user.user_id,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email_id": user.email_id,
                "is_private": user.is_private or False,
                "is_verified": user.is_verified or False,
                "bio": user.bio,
                "balance": balance,
            }
            try:
                redis.set_value(
                    _user_context_key(target_user_id), target_ctx, ttl=USER_CONTEXT_CACHE_TTL
                )
            except Exception:
                pass

        if target_ctx.get("is_private", False):
            raise HTTPException(status_code=403, detail="This account is private")

    def get_user_posts(self, target_user_id: str, skip: int = 0, limit: int = 20) -> MyPostsResponse:
        """Get posts of another user (if their account is not private)."""
        if target_user_id == self.user_id:
            return self.get_my_posts(skip=skip, limit=limit)
        self._check_user_privacy(target_user_id)
        rows, total = self.post_repo.get_my_posts(target_user_id, skip=skip, limit=limit)
        posts = [_build_post_response(row) for row in rows]
        return MyPostsResponse(posts=posts, total=total, skip=skip, limit=limit)

    def get_user_reshared_posts(self, target_user_id: str, skip: int = 0, limit: int = 20) -> ResharedPostsResponse:
        """Get reshared posts of another user (if their account is not private)."""
        if target_user_id == self.user_id:
            return self.get_reshared_posts(skip=skip, limit=limit)
        self._check_user_privacy(target_user_id)
        rows, total = self.post_repo.get_user_reshared_posts(
            target_user_id, self.user_id, skip=skip, limit=limit
        )
        posts = [_build_post_response(row) for row in rows]
        return ResharedPostsResponse(posts=posts, total=total, skip=skip, limit=limit)

    # ── Feed ──────────────────────────────────────────────────────────────────

    def get_feed(self, skip: int = 0, limit: int = 20) -> FeedResponse:
        rows, total = self.post_repo.get_feed_posts(self.user_id, skip=skip, limit=limit)
        posts = [_build_post_response(row) for row in rows]
        return FeedResponse(posts=posts, total=total, skip=skip, limit=limit)

    # ── Reshared Posts ────────────────────────────────────────────────────────

    def get_reshared_posts(self, skip: int = 0, limit: int = 20) -> ResharedPostsResponse:
        rows, total = self.post_repo.get_reshared_posts(self.user_id, skip=skip, limit=limit)
        posts = [_build_post_response(row) for row in rows]
        return ResharedPostsResponse(posts=posts, total=total, skip=skip, limit=limit)

    # ── Like Operations ───────────────────────────────────────────────────────

    def like_post(self, post_id: str) -> int:
        post = self.post_repo.get_post_by_id(post_id)
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        existing = self.like_repo.get_like(self.user_id, post_id)
        if existing:
            raise HTTPException(status_code=409, detail="Already liked this post")
        like = Like(
            like_id="like_" + str(ulid.new()),
            user_id=self.user_id,
            post_id=post_id,
            created_at=datetime.datetime.utcnow(),
        )
        self.like_repo.create_like(like)
        create_notification(
            self.db,
            recipient_id=post.author_id,
            actor_id=self.user_id,
            notif_type="like",
            post_id=post_id,
            message="liked your post",
        )
        return self.like_repo.get_like_count(post_id)

    def unlike_post(self, post_id: str) -> int:
        like = self.like_repo.get_like(self.user_id, post_id)
        if not like:
            raise HTTPException(status_code=404, detail="Like not found")
        self.like_repo.delete_like(like)
        return self.like_repo.get_like_count(post_id)

    # ── Comment Operations ────────────────────────────────────────────────────

    def add_comment(self, post_id: str, payload: CreateCommentRequest) -> Comment:
        post = self.post_repo.get_post_by_id(post_id)
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        comment = Comment(
            comment_id="cmt_" + str(ulid.new()),
            user_id=self.user_id,
            post_id=post_id,
            text=payload.text,
            created_at=datetime.datetime.utcnow(),
            updated_at=datetime.datetime.utcnow(),
        )
        saved_comment = self.comment_repo.create_comment(comment)
        create_notification(
            self.db,
            recipient_id=post.author_id,
            actor_id=self.user_id,
            notif_type="comment",
            post_id=post_id,
            message="commented on your post",
        )
        return saved_comment

    def delete_comment(self, post_id: str, comment_id: str) -> bool:
        comment = self.comment_repo.get_comment_by_id(comment_id)
        if not comment:
            raise HTTPException(status_code=404, detail="Comment not found")
        if comment.post_id != post_id:
            raise HTTPException(status_code=400, detail="Comment does not belong to this post")
        if comment.user_id != self.user_id:
            raise HTTPException(status_code=403, detail="Not authorised to delete this comment")
        return self.comment_repo.delete_comment(comment)

    def get_comments(self, post_id: str, skip: int = 0, limit: int = 50) -> CommentListResponse:
        post = self.post_repo.get_post_by_id(post_id)
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        comments, total = self.comment_repo.get_comments_for_post(post_id, skip=skip, limit=limit)
        return CommentListResponse(
            comments=[CommentResponse.model_validate(c) for c in comments],
            total=total,
            skip=skip,
            limit=limit,
        )

    # ── Reshare Operations ────────────────────────────────────────────────────

    def reshare_post(self, post_id: str) -> int:
        post = self.post_repo.get_post_by_id(post_id)
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        if post.author_id == self.user_id:
            raise HTTPException(status_code=400, detail="Cannot reshare your own post")
        existing = self.reshare_repo.get_reshare(self.user_id, post_id)
        if existing:
            raise HTTPException(status_code=409, detail="Already reshared this post")
        reshare = Reshare(
            reshare_id="rs_" + str(ulid.new()),
            user_id=self.user_id,
            post_id=post_id,
            created_at=datetime.datetime.utcnow(),
        )
        self.reshare_repo.create_reshare(reshare)
        create_notification(
            self.db,
            recipient_id=post.author_id,
            actor_id=self.user_id,
            notif_type="reshare",
            post_id=post_id,
            message="reshared your post",
        )
        return self.reshare_repo.get_reshare_count(post_id)

    def unreshare_post(self, post_id: str) -> int:
        reshare = self.reshare_repo.get_reshare(self.user_id, post_id)
        if not reshare:
            raise HTTPException(status_code=404, detail="Reshare not found")
        self.reshare_repo.delete_reshare(reshare)
        return self.reshare_repo.get_reshare_count(post_id)
