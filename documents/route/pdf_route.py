from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from documents.service.pdf_service import PdfService
from documents.service.document_service import DocumentService
from middleware import document_access_validator
from core.db_client import get_db

pdf_router = APIRouter(prefix="/documents/{doc_id}/pdfs", tags=["pdfs"])

@pdf_router.get("", dependencies=[Depends(document_access_validator)])
def get_pdf_download_url(doc_id: str, request: Request, db: Session = Depends(get_db)):
    """Get a temporary download URL for the pdf file."""
    try:
        document_service = DocumentService(db, request)
        document = document_service.get_document_by_id(doc_id)
        if document.status == "active":
            og_doc_id = document.original_document_id
            if not og_doc_id:
                raise HTTPException(
                    status_code=400,
                    detail="Document has no original document; PDF not available."
                )
            path_id = og_doc_id
        else:
            path_id = doc_id
        pdf_service = PdfService()
        pdf_download_url = pdf_service.get_pdf_download_url(path_id)
        return {
            "message": "PDF download URL generated",
            "document_id": doc_id,
            "pdf_download_url": pdf_download_url,
            "status_code": 200,
            "success": True
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
