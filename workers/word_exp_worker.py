"""
Consumes ai-operations (explain_word.completed, explain_word.stream.completed)
and persists WordExplanation records to the database.

Replaces background thread persistence in document_service.py.

Usage:
    python -m workers.word_exp_worker
"""

import logging
import datetime

from events.consumer import BaseConsumer
from events.config import CONSUMER_GROUP_WORD_EXPLANATION
from events.topics import AI_OPERATIONS, AI_OPERATIONS_DLQ
from core.db_client import SessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class WordExplanationWorker(BaseConsumer):
    def __init__(self):
        super().__init__(
            group_id=CONSUMER_GROUP_WORD_EXPLANATION,
            topics=[AI_OPERATIONS],
            dlq_topic=AI_OPERATIONS_DLQ,
            max_retries=3,
        )

    def handle(self, event_type: str, payload: dict) -> None:
        if event_type not in ("explain_word.completed", "explain_word.stream.completed"):
            return

        import ulid
        from word_explanations.data.model import WordExplanation
        from word_explanations.data.repository import WordExplanationRepository

        db = SessionLocal()
        try:
            explanation = WordExplanation(
                explanation_id="wexp_" + str(ulid.new()),
                doc_id=payload.get("doc_id", ""),
                user_id=payload.get("user_id", ""),
                word=payload.get("word", ""),
                content_id=payload.get("content_id"),
                page_id=payload.get("page_id"),
                ai_explanation=payload.get("ai_response", "").strip(),
                created_at=datetime.datetime.utcnow(),
            )
            WordExplanationRepository(db).create(explanation)
            logger.info(f"WordExplanation persisted for word='{payload.get('word')}'")
        finally:
            db.close()


if __name__ == "__main__":
    WordExplanationWorker().start()
