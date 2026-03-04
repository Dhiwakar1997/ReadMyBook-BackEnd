import datetime
from posts.data.model import Post, Like, Comment, Reshare
from users.data.model import User
from follows.data.model import Follow
from sqlalchemy.orm import Session
from sqlalchemy import func


class PostRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_post(self, post: Post) -> Post:
        self.db.add(post)
        self.db.commit()
        self.db.refresh(post)
        return post

    def get_post_by_id(self, post_id: str) -> Post | None:
        return self.db.query(Post).filter(
            Post.post_id == post_id,
            Post.is_deleted == False
        ).first()

    def get_post_meta(self, post_id: str, current_user_id: str) -> dict | None:
        like_count_sq = (
            self.db.query(Like.post_id, func.count(Like.like_id).label("like_count"))
            .group_by(Like.post_id).subquery()
        )
        comment_count_sq = (
            self.db.query(Comment.post_id, func.count(Comment.comment_id).label("comment_count"))
            .filter(Comment.is_deleted == False)
            .group_by(Comment.post_id).subquery()
        )
        reshare_count_sq = (
            self.db.query(Reshare.post_id, func.count(Reshare.reshare_id).label("reshare_count"))
            .group_by(Reshare.post_id).subquery()
        )

        row = (
            self.db.query(
                Post, User,
                func.coalesce(like_count_sq.c.like_count, 0).label("like_count"),
                func.coalesce(comment_count_sq.c.comment_count, 0).label("comment_count"),
                func.coalesce(reshare_count_sq.c.reshare_count, 0).label("reshare_count"),
            )
            .join(User, User.user_id == Post.author_id)
            .outerjoin(like_count_sq, like_count_sq.c.post_id == Post.post_id)
            .outerjoin(comment_count_sq, comment_count_sq.c.post_id == Post.post_id)
            .outerjoin(reshare_count_sq, reshare_count_sq.c.post_id == Post.post_id)
            .filter(Post.post_id == post_id, Post.is_deleted == False)
            .first()
        )

        if not row:
            return None

        post, user, like_count, comment_count, reshare_count = row
        is_liked = self.db.query(Like).filter(
            Like.user_id == current_user_id, Like.post_id == post_id
        ).first() is not None
        is_reshared = self.db.query(Reshare).filter(
            Reshare.user_id == current_user_id, Reshare.post_id == post_id
        ).first() is not None

        return {
            "post": post,
            "author": user,
            "like_count": like_count,
            "comment_count": comment_count,
            "reshare_count": reshare_count,
            "is_liked_by_me": is_liked,
            "is_reshared_by_me": is_reshared,
        }

    def update_display_name_for_doc(self, doc_id: str, display_name: str) -> int:
        count = (
            self.db.query(Post)
            .filter(Post.doc_id == doc_id, Post.is_deleted == False)
            .update({"document_display_name": display_name}, synchronize_session="fetch")
        )
        self.db.commit()
        return count

    def delete_post(self, post: Post) -> bool:
        post.is_deleted = True
        post.deleted_at = datetime.datetime.utcnow()
        self.db.commit()
        return True

    def get_my_posts(
        self,
        current_user_id: str,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[dict], int]:
        like_count_sq = (
            self.db.query(
                Like.post_id,
                func.count(Like.like_id).label("like_count")
            )
            .group_by(Like.post_id)
            .subquery()
        )

        comment_count_sq = (
            self.db.query(
                Comment.post_id,
                func.count(Comment.comment_id).label("comment_count")
            )
            .filter(Comment.is_deleted == False)
            .group_by(Comment.post_id)
            .subquery()
        )

        reshare_count_sq = (
            self.db.query(
                Reshare.post_id,
                func.count(Reshare.reshare_id).label("reshare_count")
            )
            .group_by(Reshare.post_id)
            .subquery()
        )

        base_q = (
            self.db.query(
                Post,
                User,
                func.coalesce(like_count_sq.c.like_count, 0).label("like_count"),
                func.coalesce(comment_count_sq.c.comment_count, 0).label("comment_count"),
                func.coalesce(reshare_count_sq.c.reshare_count, 0).label("reshare_count"),
            )
            .join(User, User.user_id == Post.author_id)
            .outerjoin(like_count_sq, like_count_sq.c.post_id == Post.post_id)
            .outerjoin(comment_count_sq, comment_count_sq.c.post_id == Post.post_id)
            .outerjoin(reshare_count_sq, reshare_count_sq.c.post_id == Post.post_id)
            .filter(
                Post.author_id == current_user_id,
                Post.is_deleted == False,
            )
            .order_by(Post.created_at.desc())
        )

        total = base_q.count()
        rows = base_q.offset(skip).limit(limit).all()

        post_ids = [row[0].post_id for row in rows]
        liked_post_ids = set(
            r[0] for r in self.db.query(Like.post_id)
            .filter(Like.user_id == current_user_id, Like.post_id.in_(post_ids))
            .all()
        )
        reshared_post_ids = set(
            r[0] for r in self.db.query(Reshare.post_id)
            .filter(Reshare.user_id == current_user_id, Reshare.post_id.in_(post_ids))
            .all()
        )

        result = []
        for post, user, like_count, comment_count, reshare_count in rows:
            result.append({
                "post": post,
                "author": user,
                "like_count": like_count,
                "comment_count": comment_count,
                "reshare_count": reshare_count,
                "is_liked_by_me": post.post_id in liked_post_ids,
                "is_reshared_by_me": post.post_id in reshared_post_ids,
            })

        return result, total

    def get_feed_posts(
        self,
        current_user_id: str,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[dict], int]:
        following_subq = (
            self.db.query(Follow.following_id)
            .filter(Follow.follower_id == current_user_id)
            .subquery()
        )

        like_count_sq = (
            self.db.query(
                Like.post_id,
                func.count(Like.like_id).label("like_count")
            )
            .group_by(Like.post_id)
            .subquery()
        )

        comment_count_sq = (
            self.db.query(
                Comment.post_id,
                func.count(Comment.comment_id).label("comment_count")
            )
            .filter(Comment.is_deleted == False)
            .group_by(Comment.post_id)
            .subquery()
        )

        reshare_count_sq = (
            self.db.query(
                Reshare.post_id,
                func.count(Reshare.reshare_id).label("reshare_count")
            )
            .group_by(Reshare.post_id)
            .subquery()
        )

        base_q = (
            self.db.query(
                Post,
                User,
                func.coalesce(like_count_sq.c.like_count, 0).label("like_count"),
                func.coalesce(comment_count_sq.c.comment_count, 0).label("comment_count"),
                func.coalesce(reshare_count_sq.c.reshare_count, 0).label("reshare_count"),
            )
            .join(User, User.user_id == Post.author_id)
            .outerjoin(like_count_sq, like_count_sq.c.post_id == Post.post_id)
            .outerjoin(comment_count_sq, comment_count_sq.c.post_id == Post.post_id)
            .outerjoin(reshare_count_sq, reshare_count_sq.c.post_id == Post.post_id)
            .filter(
                Post.author_id.in_(following_subq),
                Post.is_deleted == False,
            )
            .order_by(Post.created_at.desc())
        )

        total = base_q.count()
        rows = base_q.offset(skip).limit(limit).all()

        post_ids = [row[0].post_id for row in rows]
        liked_post_ids = set(
            r[0] for r in self.db.query(Like.post_id)
            .filter(Like.user_id == current_user_id, Like.post_id.in_(post_ids))
            .all()
        )
        reshared_post_ids = set(
            r[0] for r in self.db.query(Reshare.post_id)
            .filter(Reshare.user_id == current_user_id, Reshare.post_id.in_(post_ids))
            .all()
        )

        result = []
        for post, user, like_count, comment_count, reshare_count in rows:
            result.append({
                "post": post,
                "author": user,
                "like_count": like_count,
                "comment_count": comment_count,
                "reshare_count": reshare_count,
                "is_liked_by_me": post.post_id in liked_post_ids,
                "is_reshared_by_me": post.post_id in reshared_post_ids,
            })

        return result, total

    def get_user_reshared_posts(
        self,
        target_user_id: str,
        current_user_id: str,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[dict], int]:
        """Get posts reshared by a specific user."""
        user_reshare_subq = (
            self.db.query(
                Reshare.post_id,
                Reshare.created_at.label("reshare_time")
            )
            .filter(Reshare.user_id == target_user_id)
            .subquery()
        )

        like_count_sq = (
            self.db.query(
                Like.post_id,
                func.count(Like.like_id).label("like_count")
            )
            .group_by(Like.post_id)
            .subquery()
        )

        comment_count_sq = (
            self.db.query(
                Comment.post_id,
                func.count(Comment.comment_id).label("comment_count")
            )
            .filter(Comment.is_deleted == False)
            .group_by(Comment.post_id)
            .subquery()
        )

        reshare_count_sq = (
            self.db.query(
                Reshare.post_id,
                func.count(Reshare.reshare_id).label("reshare_count")
            )
            .group_by(Reshare.post_id)
            .subquery()
        )

        base_q = (
            self.db.query(
                Post,
                User,
                func.coalesce(like_count_sq.c.like_count, 0).label("like_count"),
                func.coalesce(comment_count_sq.c.comment_count, 0).label("comment_count"),
                func.coalesce(reshare_count_sq.c.reshare_count, 0).label("reshare_count"),
            )
            .join(user_reshare_subq, user_reshare_subq.c.post_id == Post.post_id)
            .join(User, User.user_id == Post.author_id)
            .outerjoin(like_count_sq, like_count_sq.c.post_id == Post.post_id)
            .outerjoin(comment_count_sq, comment_count_sq.c.post_id == Post.post_id)
            .outerjoin(reshare_count_sq, reshare_count_sq.c.post_id == Post.post_id)
            .filter(Post.is_deleted == False)
            .order_by(user_reshare_subq.c.reshare_time.desc())
        )

        total = base_q.count()
        rows = base_q.offset(skip).limit(limit).all()

        post_ids = [row[0].post_id for row in rows]
        liked_post_ids = set(
            r[0] for r in self.db.query(Like.post_id)
            .filter(Like.user_id == current_user_id, Like.post_id.in_(post_ids))
            .all()
        )
        reshared_post_ids = set(
            r[0] for r in self.db.query(Reshare.post_id)
            .filter(Reshare.user_id == current_user_id, Reshare.post_id.in_(post_ids))
            .all()
        )

        result = []
        for post, user, like_count, comment_count, reshare_count in rows:
            result.append({
                "post": post,
                "author": user,
                "like_count": like_count,
                "comment_count": comment_count,
                "reshare_count": reshare_count,
                "is_liked_by_me": post.post_id in liked_post_ids,
                "is_reshared_by_me": post.post_id in reshared_post_ids,
            })

        return result, total

    def get_reshared_posts(
        self,
        current_user_id: str,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[dict], int]:
        reshared_subq = (
            self.db.query(
                Reshare.post_id,
                func.max(Reshare.created_at).label("latest_reshare")
            )
            .group_by(Reshare.post_id)
            .subquery()
        )

        like_count_sq = (
            self.db.query(
                Like.post_id,
                func.count(Like.like_id).label("like_count")
            )
            .group_by(Like.post_id)
            .subquery()
        )

        comment_count_sq = (
            self.db.query(
                Comment.post_id,
                func.count(Comment.comment_id).label("comment_count")
            )
            .filter(Comment.is_deleted == False)
            .group_by(Comment.post_id)
            .subquery()
        )

        reshare_count_sq = (
            self.db.query(
                Reshare.post_id,
                func.count(Reshare.reshare_id).label("reshare_count")
            )
            .group_by(Reshare.post_id)
            .subquery()
        )

        base_q = (
            self.db.query(
                Post,
                User,
                func.coalesce(like_count_sq.c.like_count, 0).label("like_count"),
                func.coalesce(comment_count_sq.c.comment_count, 0).label("comment_count"),
                func.coalesce(reshare_count_sq.c.reshare_count, 0).label("reshare_count"),
            )
            .join(reshared_subq, reshared_subq.c.post_id == Post.post_id)
            .join(User, User.user_id == Post.author_id)
            .outerjoin(like_count_sq, like_count_sq.c.post_id == Post.post_id)
            .outerjoin(comment_count_sq, comment_count_sq.c.post_id == Post.post_id)
            .outerjoin(reshare_count_sq, reshare_count_sq.c.post_id == Post.post_id)
            .filter(Post.is_deleted == False)
            .order_by(reshared_subq.c.latest_reshare.desc())
        )

        total = base_q.count()
        rows = base_q.offset(skip).limit(limit).all()

        post_ids = [row[0].post_id for row in rows]
        liked_post_ids = set(
            r[0] for r in self.db.query(Like.post_id)
            .filter(Like.user_id == current_user_id, Like.post_id.in_(post_ids))
            .all()
        )
        reshared_post_ids = set(
            r[0] for r in self.db.query(Reshare.post_id)
            .filter(Reshare.user_id == current_user_id, Reshare.post_id.in_(post_ids))
            .all()
        )

        result = []
        for post, user, like_count, comment_count, reshare_count in rows:
            result.append({
                "post": post,
                "author": user,
                "like_count": like_count,
                "comment_count": comment_count,
                "reshare_count": reshare_count,
                "is_liked_by_me": post.post_id in liked_post_ids,
                "is_reshared_by_me": post.post_id in reshared_post_ids,
            })

        return result, total


class LikeRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_like(self, user_id: str, post_id: str) -> Like | None:
        return self.db.query(Like).filter(
            Like.user_id == user_id,
            Like.post_id == post_id
        ).first()

    def create_like(self, like: Like) -> Like:
        self.db.add(like)
        self.db.commit()
        self.db.refresh(like)
        return like

    def delete_like(self, like: Like) -> bool:
        self.db.delete(like)
        self.db.commit()
        return True

    def get_like_count(self, post_id: str) -> int:
        return self.db.query(func.count(Like.like_id)).filter(
            Like.post_id == post_id
        ).scalar()


class CommentRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_comment(self, comment: Comment) -> Comment:
        self.db.add(comment)
        self.db.commit()
        self.db.refresh(comment)
        return comment

    def get_comment_by_id(self, comment_id: str) -> Comment | None:
        return self.db.query(Comment).filter(
            Comment.comment_id == comment_id,
            Comment.is_deleted == False
        ).first()

    def get_comments_for_post(
        self,
        post_id: str,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[Comment], int]:
        base_q = self.db.query(Comment).filter(
            Comment.post_id == post_id,
            Comment.is_deleted == False
        ).order_by(Comment.created_at.asc())
        total = base_q.count()
        return base_q.offset(skip).limit(limit).all(), total

    def delete_comment(self, comment: Comment) -> bool:
        comment.is_deleted = True
        comment.deleted_at = datetime.datetime.utcnow()
        self.db.commit()
        return True


class ReshareRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_reshare(self, user_id: str, post_id: str) -> Reshare | None:
        return self.db.query(Reshare).filter(
            Reshare.user_id == user_id,
            Reshare.post_id == post_id
        ).first()

    def create_reshare(self, reshare: Reshare) -> Reshare:
        self.db.add(reshare)
        self.db.commit()
        self.db.refresh(reshare)
        return reshare

    def delete_reshare(self, reshare: Reshare) -> bool:
        self.db.delete(reshare)
        self.db.commit()
        return True

    def get_reshare_count(self, post_id: str) -> int:
        return self.db.query(func.count(Reshare.reshare_id)).filter(
            Reshare.post_id == post_id
        ).scalar()
