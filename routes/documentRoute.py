from fastapi import APIRouter,Depends, Request, HTTPException
from data.schemas.documentSchema import AllDocumentsResponse, CreateDocumentRequest, DocumentResponse
from middleware import  document_access_validator, verify_access_token
from services.documentService import DocumentService
from services.authService import AuthService
from data.schemas import BaseResponse
from data.dbClient import get_db
from sqlalchemy.orm import Session

document_router = APIRouter( prefix="/documents", tags=["documents"])

@document_router.get("/", response_model=AllDocumentsResponse, dependencies=[Depends(verify_access_token)])
def get_all_documents(request: Request, db: Session = Depends(get_db)):
    try:
        document_service = DocumentService(db, request)
        documents = document_service.get_all_documents()
        return AllDocumentsResponse(document_dict=documents)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@document_router.get("/{document_id}",response_model=DocumentResponse, dependencies=[Depends(document_access_validator)])
def get_document_by_id(document_id: str, request: Request, db: Session = Depends(get_db)):
    document_service = DocumentService(db, request)
    document = document_service.get_document_by_id(document_id)
    if document:
        return DocumentResponse(document=document)
    else:
        raise HTTPException(status_code=404, detail="Document not found")

@document_router.post("/", dependencies=[Depends(verify_access_token)])
def create_document( request: Request ,request_model: CreateDocumentRequest, db: Session = Depends(get_db)):
    document_service = DocumentService(db, request)
    created_document = document_service.create_document(request_model)

    auth_service = AuthService(db, request)
    auth_service.create_auth(request.state.user_id, created_document.document_id)

    return {"message": "Document created", "document_id": created_document.document_id, "status_code": 200, "success": True}

@document_router.put("/{document_id}", dependencies=[Depends(document_access_validator)])
def update_document():
    return {"message": "Document updated"}

@document_router.delete("/{document_id}")
def delete_document(document_id: str, request: Request, db: Session = Depends(get_db)):
    document_service = DocumentService(db, request)
    deleted = document_service.delete_document(document_id)
    if deleted:
        return {"message": "Document deleted", "status_code": 200, "success": True}
    else:
        raise HTTPException(status_code=404, detail="Document not found")