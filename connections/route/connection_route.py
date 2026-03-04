from fastapi import APIRouter, Depends, Request, HTTPException
from connections.data.schema import GetConnectionRequest, ConnectionResponse
from connections.service.connection_service import ConnectionService
from middleware import document_access_validator, verify_balance
from core.db_client import get_db
from sqlalchemy.orm import Session

connection_router = APIRouter(prefix="/documents/{doc_id}/connections", tags=["connections"])


@connection_router.post(
    "",
    response_model=ConnectionResponse,
    dependencies=[Depends(document_access_validator), Depends(verify_balance)],
)
def get_connections(
    doc_id: str,
    payload: GetConnectionRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Get top 5 semantically related chunks for a given content.
    Returns cached result if available, otherwise fetches from vector DB.
    """
    service = ConnectionService(db, request)
    connection = service.get_or_create_connection(
        doc_id=doc_id,
        content_id=payload.content_id,
        text=payload.text,
    )

    return connection

@connection_router.post(
    "/refresh",
    response_model=ConnectionResponse,
    dependencies=[Depends(document_access_validator), Depends(verify_balance)],
)
def refresh_connections(
    doc_id: str,
    payload: GetConnectionRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Force re-fetch connections from vector DB, updating the cached result.
    """
    service = ConnectionService(db, request)
    connection = service.refresh_connection(
        doc_id=doc_id,
        content_id=payload.content_id,
        text=payload.text,
    )
    return connection
