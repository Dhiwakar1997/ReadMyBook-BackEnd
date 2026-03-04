import datetime
from typing import Any

from bookmarks.data.model import Bookmark
from sqlalchemy.orm import Session

from shared.redis import RedisService

BOOKMARK_CACHE_TTL = 60 * 15  # 15 minutes


def _bookmarks_cache_key(user_id: str, document_id: str) -> str:
    return f"user:{user_id}:doc:{document_id}:bookmarks"


def _serialize_bookmarks(bookmarks: list[Bookmark]) -> list[dict[str, Any]]:
    return [
        {
            "bookmark_id": b.bookmark_id,
            "user_id": b.user_id,
            "document_id": b.document_id,
            "color": b.color,
            "content_id": b.content_id,
            "is_deleted": b.is_deleted,
            "created_at": b.created_at.isoformat() if b.created_at else "",
            "updated_at": b.updated_at.isoformat() if b.updated_at else "",
        }
        for b in bookmarks
    ]


def _deserialize_bookmarks(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for d in data:
        row = dict(d)
        for field in ("created_at", "updated_at"):
            if field in row and row[field]:
                try:
                    row[field] = datetime.datetime.fromisoformat(
                        str(row[field]).replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    pass
        out.append(row)
    return out


class BookmarkRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_bookmarks_by_document(self, user_id: str, document_id: str) -> list[Bookmark]:
        return (
            self.db.query(Bookmark)
            .filter(
                Bookmark.user_id == user_id,
                Bookmark.document_id == document_id,
                Bookmark.is_deleted == False,
            )
            .order_by(Bookmark.content_id)
            .all()
        )

    def get_bookmark_by_id(self, bookmark_id: str) -> Bookmark | None:
        return (
            self.db.query(Bookmark)
            .filter(Bookmark.bookmark_id == bookmark_id, Bookmark.is_deleted == False)
            .first()
        )

    def create_bookmark(self, bookmark: Bookmark) -> Bookmark:
        self.db.add(bookmark)
        self.db.commit()
        self.db.refresh(bookmark)
        return bookmark

    def update_bookmark(self, bookmark: Bookmark) -> Bookmark:
        self.db.commit()
        self.db.refresh(bookmark)
        return bookmark

    def batch_update_bookmarks(self, bookmarks: list[Bookmark]) -> list[Bookmark]:
        self.db.commit()
        for bookmark in bookmarks:
            self.db.refresh(bookmark)
        return bookmarks

    def delete_bookmark(self, bookmark: Bookmark) -> bool:
        bookmark.is_deleted = True
        self.db.commit()
        return True


class CachedBookmarkRepository:
    """
    Wraps BookmarkRepository with Redis cache for get_bookmarks_by_document.
    Key: user:{user_id}:doc:{doc_id}:bookmarks.
    Invalidates cache on create, update, batch_update, delete.
    """

    def __init__(self, db_repo: BookmarkRepository, redis: RedisService):
        self._db_repo = db_repo
        self._redis = redis

    def get_bookmarks_by_document(
        self, user_id: str, document_id: str
    ) -> list[Bookmark] | list[dict[str, Any]]:
        key = _bookmarks_cache_key(user_id, document_id)
        cached = self._redis.get_value(key)
        if cached is not None and isinstance(cached, list):
            return _deserialize_bookmarks(cached)
        bookmarks = self._db_repo.get_bookmarks_by_document(user_id, document_id)
        self._redis.set_value(key, _serialize_bookmarks(bookmarks), BOOKMARK_CACHE_TTL)
        return bookmarks

    def get_bookmark_by_id(self, bookmark_id: str) -> Bookmark | None:
        return self._db_repo.get_bookmark_by_id(bookmark_id)

    def create_bookmark(self, bookmark: Bookmark) -> Bookmark:
        created = self._db_repo.create_bookmark(bookmark)
        self._redis.delete_value(_bookmarks_cache_key(created.user_id, created.document_id))
        return created

    def update_bookmark(self, bookmark: Bookmark) -> Bookmark:
        updated = self._db_repo.update_bookmark(bookmark)
        self._redis.delete_value(_bookmarks_cache_key(bookmark.user_id, bookmark.document_id))
        return updated

    def batch_update_bookmarks(self, bookmarks: list[Bookmark]) -> list[Bookmark]:
        result = self._db_repo.batch_update_bookmarks(bookmarks)
        seen = set()
        for b in bookmarks:
            key = (b.user_id, b.document_id)
            if key not in seen:
                seen.add(key)
                self._redis.delete_value(_bookmarks_cache_key(b.user_id, b.document_id))
        return result

    def delete_bookmark(self, bookmark: Bookmark) -> bool:
        outcome = self._db_repo.delete_bookmark(bookmark)
        self._redis.delete_value(_bookmarks_cache_key(bookmark.user_id, bookmark.document_id))
        return outcome
