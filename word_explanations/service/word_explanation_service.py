from word_explanations.data.model import WordExplanation
from word_explanations.data.repository import WordExplanationRepository, CachedWordExplanationRepository
from sqlalchemy.orm import Session
from fastapi import Request
from shared.redis import RedisService
import ulid
import datetime


class WordExplanationService:
    def __init__(self, db: Session, request: Request):
        self.repository = CachedWordExplanationRepository(
            WordExplanationRepository(db), RedisService()
        )
        self.request = request

    def save_explanation(self, doc_id: str, word: str, content_id: int, page_id: int, ai_explanation: str) -> WordExplanation:
        explanation = WordExplanation(
            explanation_id="wexp_" + str(ulid.new()),
            doc_id=doc_id,
            user_id=self.request.state.user_id,
            word=word,
            content_id=content_id,
            page_id=page_id,
            ai_explanation=ai_explanation,
            created_at=datetime.datetime.utcnow(),
        )
        return self.repository.create(explanation)

    def get_explanations(self, doc_id: str, page_offset: int = 0, window_size: int = 10) -> tuple[list[WordExplanation], int]:
        return self.repository.get_by_page_window(
            doc_id=doc_id,
            user_id=self.request.state.user_id,
            page_offset=page_offset,
            window_size=window_size,
        )
