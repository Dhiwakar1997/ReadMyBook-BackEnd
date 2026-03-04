from fastapi import APIRouter, Depends, Request, Query
from word_explanations.data.schema import WordExplanationsResponse
from word_explanations.service.word_explanation_service import WordExplanationService
from middleware import document_access_validator
from core.db_client import get_db
from sqlalchemy.orm import Session

word_explanation_router = APIRouter(
    prefix="/documents/{doc_id}/word-explanations",
    tags=["word-explanations"],
)


@word_explanation_router.get(
    "",
    response_model=WordExplanationsResponse,
    dependencies=[Depends(document_access_validator)],
)
def get_word_explanations(
    doc_id: str,
    request: Request,
    page_offset: int = Query(0, ge=0),
    window_size: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    service = WordExplanationService(db, request)
    explanations, total = service.get_explanations(
        doc_id=doc_id,
        page_offset=page_offset,
        window_size=window_size,
    )
    return WordExplanationsResponse(
        explanations=explanations,
        total=total,
        page_offset=page_offset,
        window_size=window_size,
    )
