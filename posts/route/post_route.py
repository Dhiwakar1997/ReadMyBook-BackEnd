from typing import Optional
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from posts.data.schema import (
    CreatePostRequest, CreateCommentRequest,
    FeedResponse, MyPostsResponse, ResharedPostsResponse,
    PostActionResponse, LikeActionResponse, ReshareActionResponse,
    CommentListResponse, CommentResponse, PostResponse,
)
from posts.service.post_service import PostService
from middleware import verify_access_token
from core.db_client import get_db

post_router = APIRouter(prefix="/posts", tags=["posts"])


# ── Post CRUD ─────────────────────────────────────────────────────────────────

@post_router.post("", status_code=201, dependencies=[Depends(verify_access_token)])
def create_post(payload: CreatePostRequest, request: Request, db: Session = Depends(get_db)):
    service = PostService(db, request)
    post = service.create_post(payload)
    return {"message": "Post created", "post_id": post.post_id, "success": True, "status_code": 201}


@post_router.delete("/{post_id}", response_model=PostActionResponse, dependencies=[Depends(verify_access_token)])
def delete_post(post_id: str, request: Request, db: Session = Depends(get_db)):
    service = PostService(db, request)
    service.delete_post(post_id)
    return PostActionResponse(message="Post deleted", success=True, status_code=200)


# ── My Posts, Feed & Reshared — defined before /{post_id} to avoid path collision

@post_router.get("", response_model=MyPostsResponse, dependencies=[Depends(verify_access_token)])
def get_my_posts(
    request: Request,
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 20,
    user_id: Optional[str] = Query(None, description="View posts of another user"),
):
    service = PostService(db, request)
    if user_id:
        return service.get_user_posts(user_id, skip=skip, limit=limit)
    return service.get_my_posts(skip=skip, limit=limit)


@post_router.get("/feed", response_model=FeedResponse, dependencies=[Depends(verify_access_token)])
def get_feed(request: Request, db: Session = Depends(get_db), skip: int = 0, limit: int = 20):
    service = PostService(db, request)
    return service.get_feed(skip=skip, limit=limit)


@post_router.get("/reshared", response_model=ResharedPostsResponse, dependencies=[Depends(verify_access_token)])
def get_reshared_posts(
    request: Request,
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 20,
    user_id: Optional[str] = Query(None, description="View reshared posts of another user"),
):
    service = PostService(db, request)
    if user_id:
        return service.get_user_reshared_posts(user_id, skip=skip, limit=limit)
    return service.get_reshared_posts(skip=skip, limit=limit)


@post_router.get("/{post_id}", response_model=PostResponse, dependencies=[Depends(verify_access_token)])
def get_post(post_id: str, request: Request, db: Session = Depends(get_db)):
    return PostService(db, request).get_post(post_id)


# ── Like Operations ───────────────────────────────────────────────────────────

@post_router.post("/{post_id}/like", response_model=LikeActionResponse, dependencies=[Depends(verify_access_token)])
def like_post(post_id: str, request: Request, db: Session = Depends(get_db)):
    service = PostService(db, request)
    new_count = service.like_post(post_id)
    return LikeActionResponse(message="Post liked", success=True, status_code=200, like_count=new_count)


@post_router.delete("/{post_id}/like", response_model=LikeActionResponse, dependencies=[Depends(verify_access_token)])
def unlike_post(post_id: str, request: Request, db: Session = Depends(get_db)):
    service = PostService(db, request)
    new_count = service.unlike_post(post_id)
    return LikeActionResponse(message="Post unliked", success=True, status_code=200, like_count=new_count)


# ── Comment Operations ────────────────────────────────────────────────────────

@post_router.get("/{post_id}/comments", response_model=CommentListResponse, dependencies=[Depends(verify_access_token)])
def get_comments(post_id: str, request: Request, db: Session = Depends(get_db), skip: int = 0, limit: int = 50):
    service = PostService(db, request)
    return service.get_comments(post_id, skip=skip, limit=limit)


@post_router.post("/{post_id}/comments", response_model=CommentResponse, status_code=201, dependencies=[Depends(verify_access_token)])
def add_comment(post_id: str, payload: CreateCommentRequest, request: Request, db: Session = Depends(get_db)):
    service = PostService(db, request)
    comment = service.add_comment(post_id, payload)
    return CommentResponse.model_validate(comment)


@post_router.delete("/{post_id}/comments/{comment_id}", response_model=PostActionResponse, dependencies=[Depends(verify_access_token)])
def delete_comment(post_id: str, comment_id: str, request: Request, db: Session = Depends(get_db)):
    service = PostService(db, request)
    service.delete_comment(post_id, comment_id)
    return PostActionResponse(message="Comment deleted", success=True, status_code=200)


# ── Reshare Operations ────────────────────────────────────────────────────────

@post_router.post("/{post_id}/reshare", response_model=ReshareActionResponse, dependencies=[Depends(verify_access_token)])
def reshare_post(post_id: str, request: Request, db: Session = Depends(get_db)):
    service = PostService(db, request)
    new_count = service.reshare_post(post_id)
    return ReshareActionResponse(message="Post reshared", success=True, status_code=200, reshare_count=new_count)


@post_router.delete("/{post_id}/reshare", response_model=ReshareActionResponse, dependencies=[Depends(verify_access_token)])
def unreshare_post(post_id: str, request: Request, db: Session = Depends(get_db)):
    service = PostService(db, request)
    new_count = service.unreshare_post(post_id)
    return ReshareActionResponse(message="Post unreshared", success=True, status_code=200, reshare_count=new_count)
