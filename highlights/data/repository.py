from highlights.data.model import Highlight
from sqlalchemy.orm import Session


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
