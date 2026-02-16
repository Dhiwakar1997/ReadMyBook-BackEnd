from bookmarks.data.model import Bookmark
from bookmarks.data.repository import BookmarkRepository
from bookmarks.data.schema import (
    CreateBookmarkRequest,
    UpdateBookmarkRequest,
    BatchUpdateBookmarkRequest,
)
from sqlalchemy.orm import Session
from fastapi import Request, HTTPException

import ulid
import datetime


class BookmarkService:
    def __init__(self, db: Session, request: Request):
        self.bookmark_repository = BookmarkRepository(db)
        self.request = request
        self.user_id = request.state.user_id

    def get_bookmarks(self, document_id: str) -> list[Bookmark]:
        return self.bookmark_repository.get_bookmarks_by_document(
            self.user_id, document_id
        )

    def create_bookmark(
        self, document_id: str, payload: CreateBookmarkRequest
    ) -> Bookmark:
        bookmark = Bookmark(
            bookmark_id="bm_" + str(ulid.new()),
            user_id=self.user_id,
            document_id=document_id,
            color=payload.color,
            content_id=payload.content_id,
            created_at=datetime.datetime.utcnow(),
            updated_at=datetime.datetime.utcnow(),
        )
        return self.bookmark_repository.create_bookmark(bookmark)

    def update_bookmark(
        self, bookmark_id: str, payload: UpdateBookmarkRequest
    ) -> Bookmark:
        bookmark = self.bookmark_repository.get_bookmark_by_id(bookmark_id)
        if not bookmark:
            raise HTTPException(status_code=404, detail="Bookmark not found")
        if bookmark.user_id != self.user_id:
            raise HTTPException(status_code=403, detail="Not authorised")

        bookmark.color = payload.color
        bookmark.updated_at = datetime.datetime.utcnow()

        return self.bookmark_repository.update_bookmark(bookmark)

    def batch_update_bookmarks(
        self, payload: BatchUpdateBookmarkRequest
    ) -> list[Bookmark]:
        updated: list[Bookmark] = []
        for item in payload.bookmarks:
            bookmark = self.bookmark_repository.get_bookmark_by_id(item.bookmark_id)
            if not bookmark:
                raise HTTPException(
                    status_code=404,
                    detail=f"Bookmark {item.bookmark_id} not found",
                )
            if bookmark.user_id != self.user_id:
                raise HTTPException(status_code=403, detail="Not authorised")

            bookmark.color = item.color
            bookmark.updated_at = datetime.datetime.utcnow()
            updated.append(bookmark)

        return self.bookmark_repository.batch_update_bookmarks(updated)

    def delete_bookmark(self, bookmark_id: str) -> bool:
        bookmark = self.bookmark_repository.get_bookmark_by_id(bookmark_id)
        if not bookmark:
            raise HTTPException(status_code=404, detail="Bookmark not found")
        if bookmark.user_id != self.user_id:
            raise HTTPException(status_code=403, detail="Not authorised")

        return self.bookmark_repository.delete_bookmark(bookmark)
