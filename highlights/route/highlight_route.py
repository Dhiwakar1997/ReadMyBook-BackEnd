from fastapi import APIRouter, Depends, Request
from highlights.data.schema import (
    HighlightListResponse,
    HighlightResponse,
    CreateHighlightRequest,
    UpdateHighlightRequest,
)
from highlights.service.highlight_service import HighlightService
from middleware import document_access_validator
from core.db_client import get_db
from sqlalchemy.orm import Session

highlight_router = APIRouter(prefix="/documents/{document_id}/highlights", tags=["highlights"])


@highlight_router.get(
    "",
    response_model=HighlightListResponse,
    dependencies=[Depends(document_access_validator)],
)
def get_highlights(
    document_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    service = HighlightService(db, request)
    highlights = service.get_highlights(document_id)
    return HighlightListResponse(highlights=highlights)


@highlight_router.post(
    "",
    response_model=HighlightResponse,
    status_code=201,
    dependencies=[Depends(document_access_validator)],
)
def create_highlight(
    document_id: str,
    payload: CreateHighlightRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    service = HighlightService(db, request)
    highlight = service.create_highlight(document_id, payload)
    return highlight


@highlight_router.patch(
    "/{highlight_id}",
    response_model=HighlightResponse,
    dependencies=[Depends(document_access_validator)],
)
def update_highlight(
    document_id: str,
    highlight_id: str,
    payload: UpdateHighlightRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    service = HighlightService(db, request)
    highlight = service.update_highlight(highlight_id, payload)
    return highlight


@highlight_router.delete(
    "/{highlight_id}",
    dependencies=[Depends(document_access_validator)],
)
def delete_highlight(
    document_id: str,
    highlight_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    service = HighlightService(db, request)
    service.delete_highlight(highlight_id)
    return {"message": "Highlight deleted", "status_code": 200, "success": True}
