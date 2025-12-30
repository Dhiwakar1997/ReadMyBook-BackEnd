from fastapi import APIRouter, Depends, HTTPException
from services.pdfService import PdfService
from middleware import document_access_validator

pdf_router = APIRouter(prefix="/documents/{document_id}/pdfs", tags=["pdfs"])

@pdf_router.get("", dependencies=[Depends(document_access_validator)])
def get_pdf_download_url(document_id: str):
    """Get a temporary download URL for the pdf file."""
    try:
        pdf_service = PdfService()
        pdf_download_url = pdf_service.get_pdf_download_url(document_id)
        return {"pdf_download_url": pdf_download_url,"status_code": 200,"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))