from fastapi import APIRouter, Depends, Request, HTTPException, Query
from fastapi.responses import StreamingResponse
from documents.data.schema import AllDocumentsResponse, CreateDocumentRequest, DocumentResponse, UpdateDocumentRequest, AskDocumentRequest, ExplainWordDocumentRequest, ShareDocumentRequest, ShareDocumentResponse, GetSharedUsersResponse, DocumentSearchResponse, CreateAccessRequestRequest, PendingRequestsResponse
from middleware import document_access_validator, verify_access_token, verify_balance, owner_access_validator
from documents.service.document_service import DocumentService
from documents.service.document_access_service import DocumentAccessService
from documents.service.document_access_request_service import DocumentAccessRequestService
from shared.azure_blob import AzureBlobService
from core.schemas import BaseResponse
from core.db_client import get_db
from sqlalchemy.orm import Session

document_router = APIRouter(prefix="/documents", tags=["documents"])

@document_router.get("", response_model=AllDocumentsResponse, dependencies=[Depends(verify_access_token)])
def get_all_documents(request: Request, db: Session = Depends(get_db)):
    try:
        document_service = DocumentService(db, request)
        documents = document_service.get_all_documents()
        return AllDocumentsResponse(document_dict=documents)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@document_router.get("/search", response_model=DocumentSearchResponse, dependencies=[Depends(verify_access_token)])
def search_documents(q: str, request: Request, db: Session = Depends(get_db)):
    service = DocumentService(db, request)
    results = service.search_documents(q)
    return DocumentSearchResponse(results=results)

@document_router.get("/access-requests", response_model=PendingRequestsResponse, dependencies=[Depends(verify_access_token)])
def get_pending_requests(request: Request, db: Session = Depends(get_db)):
    service = DocumentAccessRequestService(db, request)
    return service.get_pending_requests()

@document_router.get("/{document_id}", response_model=DocumentResponse, dependencies=[Depends(document_access_validator)])
def get_document_by_id(document_id: str, request: Request, db: Session = Depends(get_db)):
    document_service = DocumentService(db, request)
    document = document_service.get_document_by_id(document_id)
    if document:
        return DocumentResponse(document=document)
    else:
        raise HTTPException(status_code=404, detail="Document not found")

@document_router.post("", dependencies=[Depends(verify_access_token)])
def create_document(request: Request, request_model: CreateDocumentRequest, db: Session = Depends(get_db)):
    document_service = DocumentService(db, request)
    created_document = document_service.create_document(request_model)

    document_access_service = DocumentAccessService(db, request)
    document_access_service.create_document_access(request.state.user_id, created_document.document_id)

    azure_blob_service = AzureBlobService()
    upload_url = azure_blob_service.generate_upload_url(container_name=f"pdfs/{created_document.document_id}", file_name=f"{created_document.document_id}.pdf")

    return {"message": "Document created", "document_id": created_document.document_id, "upload_url": upload_url, "status_code": 200, "success": True}

@document_router.patch("/{document_id}", dependencies=[Depends(owner_access_validator)])
def update_document(document_id: str, request_model: UpdateDocumentRequest, request: Request, db: Session = Depends(get_db)):
    document_service = DocumentService(db, request)
    updated_document = document_service.update_document(document_id, request_model)
    if updated_document:
        return {"message": "Document updated", "document_id": updated_document.document_id, "status_code": 200, "success": True}
    else:
        raise HTTPException(status_code=404, detail="Document not found")

@document_router.post("/{document_id}/access-request", dependencies=[Depends(verify_access_token)])
def create_access_request(document_id: str, payload: CreateAccessRequestRequest, request: Request, db: Session = Depends(get_db)):
    service = DocumentAccessRequestService(db, request)
    service.create_access_request(document_id, payload.message)
    return {"message": "Access request sent", "status_code": 200, "success": True}

@document_router.delete("/{document_id}/access-requests/{request_id}", dependencies=[Depends(owner_access_validator)])
def resolve_access_request(document_id: str, request_id: str, request: Request, accept: bool = Query(False), db: Session = Depends(get_db)):
    service = DocumentAccessRequestService(db, request)
    service.resolve_request(request_id, accept)
    msg = "Request accepted and access granted" if accept else "Request cancelled"
    return {"message": msg, "status_code": 200, "success": True}

@document_router.delete("/{document_id}/access-requests/{request_id}/cancel", dependencies=[Depends(verify_access_token)])
def cancel_access_request(document_id: str, request_id: str, request: Request, db: Session = Depends(get_db)):
    service = DocumentAccessRequestService(db, request)
    service.cancel_request(request_id)
    return {"message": "Access request cancelled", "status_code": 200, "success": True}

@document_router.delete("/{document_id}",dependencies=[Depends(owner_access_validator)])
def delete_document(document_id: str, request: Request, db: Session = Depends(get_db)):
    document_service = DocumentService(db, request)
    deleted = document_service.delete_document(document_id)
    if deleted:
        return {"message": "Document deleted", "status_code": 200, "success": True}
    else:
        raise HTTPException(status_code=404, detail="Document not found")

@document_router.post("/{document_id}/share", response_model=ShareDocumentResponse, dependencies=[Depends(owner_access_validator)])
def share_document(document_id: str, payload: ShareDocumentRequest, request: Request, db: Session = Depends(get_db)):
    service = DocumentAccessService(db, request)
    shared_with = service.share_document(document_id, payload.user_ids)
    
    return ShareDocumentResponse(
        message=f"Document shared with {len(shared_with)} user(s)",
        success=True,
        status_code=200,
        shared_with=shared_with,
    )

@document_router.get("/{document_id}/share", response_model=GetSharedUsersResponse, dependencies=[Depends(owner_access_validator)])
def get_shared_users(document_id: str, request: Request, db: Session = Depends(get_db)):
    service = DocumentAccessService(db, request)
    shared_users = service.get_shared_users(document_id)
    return GetSharedUsersResponse(shared_users=shared_users)

@document_router.delete("/{document_id}/share", dependencies=[Depends(owner_access_validator)])
def unshare_document(document_id: str, payload: ShareDocumentRequest, request: Request, db: Session = Depends(get_db)):
    service = DocumentAccessService(db, request)
    count = service.unshare_document(document_id, payload.user_ids)
    return {"message": f"Removed access for {count} user(s)", "success": True, "status_code": 200}

@document_router.get("/{document_id}/ask", dependencies=[Depends(document_access_validator), Depends(verify_balance)])
async def ask_document(document_id: str, request_model: AskDocumentRequest, request: Request, db: Session = Depends(get_db)):
    document_service = DocumentService(db, request)
    document = await document_service.ask_document(request, document_id, request_model)
    return document

@document_router.post(
    "/{document_id}/ask/stream",
    dependencies=[Depends(document_access_validator), Depends(verify_balance)],
    summary="Ask a question about a document — SSE streaming response",
    description=(
        "Opens a Server-Sent Events stream. The client receives real-time token "
        "chunks followed by a final 'done' event containing reference_contents."
    ),
)
async def ask_document_stream(
    document_id: str,
    request_model: AskDocumentRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    document_service = DocumentService(db, request)

    return StreamingResponse(
        document_service.ask_document_stream(request, document_id, request_model),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control":     "no-cache",
            "Connection":        "keep-alive",
        },
    )

@document_router.get("/{document_id}/explain-word", dependencies=[Depends(document_access_validator), Depends(verify_balance)])
async def explain_word_text(document_id: str, request_model: ExplainWordDocumentRequest, request: Request, db: Session = Depends(get_db)):
    document_service = DocumentService(db, request)
    explanation = await document_service.explain_word_text(request, document_id, request_model)
    return explanation

@document_router.post(
    "/{document_id}/explain-word/stream",
    dependencies=[Depends(document_access_validator), Depends(verify_balance)],
    summary="Explain a word in context — SSE streaming response",
    description=(
        "Opens a Server-Sent Events stream. The client receives real-time token "
        "chunks followed by a final 'done' event containing reference_contents."
    ),
)
async def explain_word_text_stream(
    document_id: str,
    request_model: ExplainWordDocumentRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    document_service = DocumentService(db, request)

    return StreamingResponse(
        document_service.explain_word_text_stream(request, document_id, request_model),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control":     "no-cache",
            "Connection":        "keep-alive",
        },
    )
