from fastapi import APIRouter, Depends, Request
from follows.data.schema import FollowMetadataResponse, FollowListResponse, FollowActionResponse
from follows.service.follow_service import FollowService
from middleware import verify_access_token
from core.db_client import get_db
from sqlalchemy.orm import Session

follow_router = APIRouter(prefix="/follows", tags=["follows"])


@follow_router.post("/{user_id}", response_model=FollowActionResponse, dependencies=[Depends(verify_access_token)])
def follow_user(user_id: str, request: Request, db: Session = Depends(get_db)):
    service = FollowService(db, request)
    service.follow_user(user_id)
    return FollowActionResponse(message="Followed successfully", success=True, status_code=200)


@follow_router.delete("/{user_id}", response_model=FollowActionResponse, dependencies=[Depends(verify_access_token)])
def unfollow_user(user_id: str, request: Request, db: Session = Depends(get_db)):
    service = FollowService(db, request)
    service.unfollow_user(user_id)
    return FollowActionResponse(message="Unfollowed successfully", success=True, status_code=200)


@follow_router.get("/{user_id}/metadata", response_model=FollowMetadataResponse, dependencies=[Depends(verify_access_token)])
def get_follow_metadata(user_id: str, request: Request, db: Session = Depends(get_db)):
    service = FollowService(db, request)
    return service.get_metadata(user_id)


@follow_router.get("/{user_id}/followers", response_model=FollowListResponse, dependencies=[Depends(verify_access_token)])
def get_followers(user_id: str, request: Request, db: Session = Depends(get_db)):
    service = FollowService(db, request)
    return FollowListResponse(users=service.get_followers(user_id))


@follow_router.get("/{user_id}/following", response_model=FollowListResponse, dependencies=[Depends(verify_access_token)])
def get_following(user_id: str, request: Request, db: Session = Depends(get_db)):
    service = FollowService(db, request)
    return FollowListResponse(users=service.get_following(user_id))
