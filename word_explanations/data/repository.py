import datetime
from typing import Any

from word_explanations.data.model import WordExplanation
from sqlalchemy.orm import Session

from shared.redis import RedisService

WORD_EXPLANATION_CACHE_TTL = 60 * 15  # 15 minutes


def _word_explanations_cache_key(user_id: str, doc_id: str, page_offset: int, window_size: int) -> str:
    return f"user:{user_id}:doc:{doc_id}:word_explanations:{page_offset}:{window_size}"


def _word_explanations_prefix(user_id: str, doc_id: str) -> str:
    return f"user:{user_id}:doc:{doc_id}:word_explanations:"


def _serialize_explanations(items: list[WordExplanation], total: int) -> dict[str, Any]:
    return {
        "items": [
            {
                "explanation_id": e.explanation_id,
                "doc_id": e.doc_id,
                "user_id": e.user_id,
                "word": e.word,
                "content_id": e.content_id,
                "page_id": e.page_id,
                "ai_explanation": e.ai_explanation,
                "created_at": e.created_at.isoformat() if e.created_at else "",
            }
            for e in items
        ],
        "total": total,
    }


def _deserialize_explanations(data: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    items = data.get("items", [])
    total = data.get("total", 0)
    out = []
    for d in items:
        row = dict(d)
        if "created_at" in row and row["created_at"]:
            try:
                row["created_at"] = datetime.datetime.fromisoformat(
                    str(row["created_at"]).replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass
        out.append(row)
    return out, total


class WordExplanationRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, explanation: WordExplanation) -> WordExplanation:
        self.db.add(explanation)
        self.db.commit()
        self.db.refresh(explanation)
        return explanation

    def get_by_page_window(self, doc_id: str, user_id: str, page_offset: int, window_size: int) -> tuple[list[WordExplanation], int]:
        query = (
            self.db.query(WordExplanation)
            .filter(
                WordExplanation.doc_id == doc_id,
                WordExplanation.user_id == user_id,
                WordExplanation.page_id >= page_offset,
                WordExplanation.page_id < page_offset + window_size,
            )
            .order_by(WordExplanation.page_id.asc(), WordExplanation.content_id.asc())
        )
        total = query.count()
        return query.all(), total


class CachedWordExplanationRepository:
    """
    Wraps WordExplanationRepository with Redis cache for get_by_page_window.
    Key: user:{user_id}:doc:{doc_id}:word_explanations:{page_offset}:{window_size}.
    Invalidates all cached windows for that user+doc on create.
    """

    def __init__(self, inner: WordExplanationRepository, redis: RedisService):
        self._db_repo = inner
        self._redis = redis

    def get_by_page_window(
        self, doc_id: str, user_id: str, page_offset: int, window_size: int
    ) -> tuple[list[WordExplanation] | list[dict[str, Any]], int]:
        key = _word_explanations_cache_key(user_id, doc_id, page_offset, window_size)
        cached = self._redis.get_value(key)
        if cached is not None and isinstance(cached, dict):
            return _deserialize_explanations(cached)
        items, total = self._db_repo.get_by_page_window(doc_id, user_id, page_offset, window_size)
        self._redis.set_value(key, _serialize_explanations(items, total), WORD_EXPLANATION_CACHE_TTL)
        return items, total

    def create(self, explanation: WordExplanation) -> WordExplanation:
        created = self._db_repo.create(explanation)
        self._redis.delete_keys_by_prefix(_word_explanations_prefix(created.user_id, created.doc_id))
        return created
