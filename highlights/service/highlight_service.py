from highlights.data.model import Highlight
from highlights.data.repository import HighlightRepository
from highlights.data.schema import CreateHighlightRequest, UpdateHighlightRequest
from sqlalchemy.orm import Session
from fastapi import Request, HTTPException

import ulid
import datetime


class HighlightService:
    def __init__(self, db: Session, request: Request):
        self.highlight_repository = HighlightRepository(db)
        self.request = request
        self.user_id = request.state.user_id

    def get_highlights(self, document_id: str) -> list[Highlight]:
        return self.highlight_repository.get_highlights_by_document(
            self.user_id, document_id
        )

    def create_highlight(
        self, document_id: str, payload: CreateHighlightRequest
    ) -> Highlight:
        highlight = Highlight(
            highlight_id="hl_" + str(ulid.new()),
            user_id=self.user_id,
            document_id=document_id,
            content_id=payload.content_id,
            page_number=payload.page_number,
            start_index=payload.start_index,
            stop_index=payload.stop_index,
            highlight_color=payload.highlight_color,
            created_at=datetime.datetime.utcnow(),
            updated_at=datetime.datetime.utcnow(),
        )
        return self.highlight_repository.create_highlight(highlight)

    def update_highlight(
        self, highlight_id: str, payload: UpdateHighlightRequest
    ) -> Highlight:
        highlight = self.highlight_repository.get_highlight_by_id(highlight_id)
        if not highlight:
            raise HTTPException(status_code=404, detail="Highlight not found")
        if highlight.user_id != self.user_id:
            raise HTTPException(status_code=403, detail="Not authorised")

        highlight.start_index = payload.start_index
        highlight.stop_index = payload.stop_index
        highlight.updated_at = datetime.datetime.utcnow()

        return self.highlight_repository.update_highlight(highlight)

    def delete_highlight(self, highlight_id: str) -> bool:
        highlight = self.highlight_repository.get_highlight_by_id(highlight_id)
        if not highlight:
            raise HTTPException(status_code=404, detail="Highlight not found")
        if highlight.user_id != self.user_id:
            raise HTTPException(status_code=403, detail="Not authorised")

        return self.highlight_repository.delete_highlight(highlight)
