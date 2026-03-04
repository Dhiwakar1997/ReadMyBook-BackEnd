import json
import datetime
from typing import Any

from highlights.data.model import Highlight
from sqlalchemy.orm import Session

from shared.redis import RedisService

# Short TTL for highlight cache (15 minutes)
HIGHLIGHT_CACHE_TTL = 60 * 15


def _highlights_cache_key(user_id: str, document_id: str) -> str:
    return f"user:{user_id}:doc:{document_id}:highlights"


def _serialize_highlights(highlights: list[Highlight]) -> list[dict[str, Any]]:
    """Serialize list of Highlight to JSON-friendly list of dicts."""
    return [
        {
            "highlight_id": h.highlight_id,
            "user_id": h.user_id,
            "document_id": h.document_id,
            "content_id": h.content_id,
            "page_number": h.page_number,
            "start_index": h.start_index,
            "stop_index": h.stop_index,
            "highlight_color": h.highlight_color,
            "created_at": h.created_at.isoformat() if h.created_at else "",
            "updated_at": h.updated_at.isoformat() if h.updated_at else "",
        }
        for h in highlights
    ]


def _deserialize_highlights(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return list of dicts with datetime strings parsed for API compatibility."""
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


class HighlightRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_highlights_by_document(self, user_id: str, document_id: str) -> list[Highlight]:
        return (
            self.db.query(Highlight)
            .filter(
                Highlight.user_id == user_id,
                Highlight.document_id == document_id,
            )
            .order_by(Highlight.page_number, Highlight.content_id, Highlight.start_index)
            .all()
        )

    def get_highlight_by_id(self, highlight_id: str) -> Highlight | None:
        return (
            self.db.query(Highlight)
            .filter(Highlight.highlight_id == highlight_id)
            .first()
        )

    def create_highlight(self, highlight: Highlight) -> Highlight:
        self.db.add(highlight)
        self.db.commit()
        self.db.refresh(highlight)
        return highlight

    def update_highlight(self, highlight: Highlight) -> Highlight:
        self.db.commit()
        self.db.refresh(highlight)
        return highlight

    def delete_highlight(self, highlight: Highlight) -> bool:
        self.db.delete(highlight)
        self.db.commit()
        return True


class CachedHighlightRepository:
    """
    Wraps HighlightRepository with Redis cache for get_highlights_by_document.
    Key: user:{user_id}:highlights:{doc_id}. Invalidates cache on create/update/delete.
    """

    def __init__(self, inner: HighlightRepository, redis: RedisService):
        self._db_repo = inner
        self._redis = redis

    def get_highlights_by_document(self, user_id: str, document_id: str) -> list[Highlight] | list[dict[str, Any]]:
        key = _highlights_cache_key(user_id, document_id)
        cached = self._redis.get_value(key)
        if cached is not None and isinstance(cached, list):
            return _deserialize_highlights(cached)
        highlights = self._db_repo.get_highlights_by_document(user_id, document_id)
        self._redis.set_value(key, _serialize_highlights(highlights), HIGHLIGHT_CACHE_TTL)
        return highlights

    def get_highlight_by_id(self, highlight_id: str) -> Highlight | None:
        return self._db_repo.get_highlight_by_id(highlight_id)

    def create_highlight(self, highlight: Highlight) -> Highlight:
        created = self._db_repo.create_highlight(highlight)
        self._redis.delete_value(_highlights_cache_key(highlight.user_id, highlight.document_id))
        return created

    def update_highlight(self, highlight: Highlight) -> Highlight:
        updated = self._db_repo.update_highlight(highlight)
        self._redis.delete_value(_highlights_cache_key(highlight.user_id, highlight.document_id))
        return updated

    def delete_highlight(self, highlight: Highlight) -> bool:
        result = self._db_repo.delete_highlight(highlight)
        self._redis.delete_value(_highlights_cache_key(highlight.user_id, highlight.document_id))
        return result
