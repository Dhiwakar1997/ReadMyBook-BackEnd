from follows.data.model import Follow
from users.data.model import User
from sqlalchemy.orm import Session
from sqlalchemy import func


class FollowRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_follow(self, follow: Follow) -> Follow:
        self.db.add(follow)
        self.db.commit()
        self.db.refresh(follow)
        return follow

    def delete_follow(self, follower_id: str, following_id: str) -> bool:
        follow = self.db.query(Follow).filter(
            Follow.follower_id == follower_id,
            Follow.following_id == following_id
        ).first()
        if not follow:
            return False
        self.db.delete(follow)
        self.db.commit()
        return True

    def get_follow(self, follower_id: str, following_id: str):
        return self.db.query(Follow).filter(
            Follow.follower_id == follower_id,
            Follow.following_id == following_id
        ).first()

    def get_follower_count(self, user_id: str) -> int:
        return self.db.query(func.count(Follow.id)).filter(
            Follow.following_id == user_id
        ).scalar()

    def get_following_count(self, user_id: str) -> int:
        return self.db.query(func.count(Follow.id)).filter(
            Follow.follower_id == user_id
        ).scalar()

    def get_followers(self, user_id: str) -> list:
        return (
            self.db.query(User)
            .join(Follow, Follow.follower_id == User.user_id)
            .filter(Follow.following_id == user_id)
            .all()
        )

    def get_following(self, user_id: str) -> list:
        return (
            self.db.query(User)
            .join(Follow, Follow.following_id == User.user_id)
            .filter(Follow.follower_id == user_id)
            .all()
        )
