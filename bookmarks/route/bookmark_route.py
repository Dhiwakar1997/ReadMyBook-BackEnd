from fastapi import APIRouter, Depends, Request
from bookmarks.data.schema import (
    BookmarkListResponse,
    BookmarkResponse,
    CreateBookmarkRequest,
    UpdateBookmarkRequest,
    BatchUpdateBookmarkRequest,
)
from bookmarks.service.bookmark_service import BookmarkService
from middleware import verify_access_token, document_access_validator
from core.db_client import get_db
from sqlalchemy.orm import Session

bookmark_router = APIRouter(prefix="/documents/{document_id}/bookmarks", tags=["bookmarks"])


@bookmark_router.get(
    "",
    response_model=BookmarkListResponse,
    dependencies=[Depends(document_access_validator)],
)
def get_bookmarks(
    document_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    service = BookmarkService(db, request)
    bookmarks = service.get_bookmarks(document_id)
    return BookmarkListResponse(bookmarks=bookmarks)


@bookmark_router.post(
    "",
    response_model=BookmarkResponse,
    status_code=201,
    dependencies=[Depends(document_access_validator)],
)
def create_bookmark(
    document_id: str,
    payload: CreateBookmarkRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    service = BookmarkService(db, request)
    bookmark = service.create_bookmark(document_id, payload)
    return bookmark


@bookmark_router.patch(
    "/{bookmark_id}",
    response_model=BookmarkResponse,
    dependencies=[Depends(document_access_validator)],
)
def update_bookmark(
    document_id: str,
    bookmark_id: str,
    payload: UpdateBookmarkRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    service = BookmarkService(db, request)
    bookmark = service.update_bookmark(bookmark_id, payload)
    return bookmark


@bookmark_router.patch(
    "",
    response_model=BookmarkListResponse,
    dependencies=[Depends(document_access_validator)],
)
def batch_update_bookmarks(
    document_id: str,
    payload: BatchUpdateBookmarkRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    service = BookmarkService(db, request)
    bookmarks = service.batch_update_bookmarks(payload)
    return BookmarkListResponse(bookmarks=bookmarks)


@bookmark_router.delete(
    "/{bookmark_id}",
    dependencies=[Depends(document_access_validator)],
)
def delete_bookmark(
    document_id: str,
    bookmark_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    service = BookmarkService(db, request)
    service.delete_bookmark(bookmark_id)
    return {"message": "Bookmark deleted", "status_code": 200, "success": True}
