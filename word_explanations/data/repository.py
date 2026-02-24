from word_explanations.data.model import WordExplanation
from sqlalchemy.orm import Session


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
