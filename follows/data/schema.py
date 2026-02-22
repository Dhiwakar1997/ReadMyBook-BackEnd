from pydantic import BaseModel
from typing import Optional


class FollowMetadataResponse(BaseModel):
    user_id: str
    follower_count: int
    following_count: int


class FollowUserResponse(BaseModel):
    user_id: str
    first_name: str
    last_name: Optional[str] = None

    class Config:
        from_attributes = True


class FollowListResponse(BaseModel):
    users: list[FollowUserResponse]


class FollowActionResponse(BaseModel):
    message: str
    success: bool
    status_code: int
