from follows.data.model import Follow
from follows.data.repository import FollowRepository
from sqlalchemy.orm import Session
from fastapi import Request, HTTPException
import ulid
import datetime


class FollowService:
    def __init__(self, db: Session, request: Request):
        self.follow_repository = FollowRepository(db)
        self.request = request
        self.user_id = request.state.user_id

    def follow_user(self, target_user_id: str):
        if self.user_id == target_user_id:
            raise HTTPException(status_code=400, detail="Cannot follow yourself")
        existing = self.follow_repository.get_follow(self.user_id, target_user_id)
        if existing:
            raise HTTPException(status_code=409, detail="Already following this user")
        follow = Follow(
            id="fw_" + str(ulid.new()),
            follower_id=self.user_id,
            following_id=target_user_id,
            created_at=datetime.datetime.utcnow(),
        )
        return self.follow_repository.create_follow(follow)

    def unfollow_user(self, target_user_id: str):
        deleted = self.follow_repository.delete_follow(self.user_id, target_user_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Follow relationship not found")
        return True

    def get_metadata(self, user_id: str):
        return {
            "user_id": user_id,
            "follower_count": self.follow_repository.get_follower_count(user_id),
            "following_count": self.follow_repository.get_following_count(user_id),
        }

    def get_followers(self, user_id: str):
        users = self.follow_repository.get_followers(user_id)
        return [{"user_id": u.user_id, "first_name": u.first_name, "last_name": u.last_name} for u in users]

    def get_following(self, user_id: str):
        users = self.follow_repository.get_following(user_id)
        return [{"user_id": u.user_id, "first_name": u.first_name, "last_name": u.last_name} for u in users]
