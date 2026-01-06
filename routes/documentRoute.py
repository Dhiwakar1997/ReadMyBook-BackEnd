from fastapi import APIRouter,Depends, Request, HTTPException
from data.schemas.documentSchema import AllDocumentsResponse, CreateDocumentRequest, DocumentResponse, UpdateDocumentRequest, AskDocumentRequest, ExplainDocumentRequest
from middleware import  document_access_validator, verify_access_token
from services.documentService import DocumentService
from services.documentAccessService import DocumentAccessService
from services.azureBlobService import AzureBlobService
from data.schemas import BaseResponse
from data.dbClient import get_db
from sqlalchemy.orm import Session

document_router = APIRouter( prefix="/documents", tags=["documents"])

@document_router.get("", response_model=AllDocumentsResponse, dependencies=[Depends(verify_access_token)])
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

@document_router.post("", dependencies=[Depends(verify_access_token)])
def create_document( request: Request ,request_model: CreateDocumentRequest, db: Session = Depends(get_db)):

    document_service = DocumentService(db, request)
    created_document = document_service.create_document(request_model)

    document_access_service = DocumentAccessService(db, request)
    document_access_service.create_document_access(request.state.user_id, created_document.document_id)

    azure_blob_service = AzureBlobService()
    upload_url = azure_blob_service.generate_upload_url(container_name=f"pdf/{created_document.document_id}", file_name=f"{created_document.document_id}.pdf")

    return {"message": "Document created", "document_id": created_document.document_id, "upload_url": upload_url, "status_code": 200, "success": True}

@document_router.patch("/{document_id}", dependencies=[Depends(document_access_validator)])
def update_document(document_id: str,request_model: UpdateDocumentRequest , request: Request, db: Session = Depends(get_db)):
    
    document_service = DocumentService(db, request)
    updated_document = document_service.update_document(document_id, request_model)
    if updated_document:
        return {"message": "Document updated", "document_id": updated_document.document_id, "status_code": 200, "success": True}
    else:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"message": "Document updated"}

@document_router.delete("/{document_id}")
def delete_document(document_id: str, request: Request, db: Session = Depends(get_db)):
    document_service = DocumentService(db, request)
    deleted = document_service.delete_document(document_id)
    if deleted:
        return {"message": "Document deleted", "status_code": 200, "success": True}
    else:
        raise HTTPException(status_code=404, detail="Document not found")

@document_router.get("/{document_id}/ask", dependencies=[Depends(document_access_validator)])
def ask_document(document_id: str ,request_model: AskDocumentRequest, request: Request, db: Session = Depends(get_db)):
    question = request_model.question
    document_service = DocumentService(db, request)
    document = document_service.ask_document(request, document_id, question)
    return document

@document_router.get("/{document_id}/explain", dependencies=[Depends(document_access_validator)])
def explain_text(document_id: str ,request_model: ExplainDocumentRequest, request: Request, db: Session = Depends(get_db)):
    text = request_model.text
    document_service = DocumentService(db, request)
    explanation = document_service.explain_text(text)
    return explanation