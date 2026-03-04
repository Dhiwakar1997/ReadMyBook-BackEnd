from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from documents.service.markdown_service import MarkdownService
from documents.service.document_service import DocumentService
from middleware import document_access_validator
from core.db_client import get_db

markdown_router = APIRouter(prefix="/documents/{doc_id}/markdowns", tags=["markdowns"])

@markdown_router.get("", dependencies=[Depends(document_access_validator)])
def get_markdown_download_url(doc_id: str, request: Request, db: Session = Depends(get_db)):
    """Get a temporary download URL for the markdown file."""
    try:
        document_service = DocumentService(db, request)
        document = document_service.get_document_by_id(doc_id)
        og_doc_id = document.original_document_id
        if not og_doc_id:
            raise HTTPException(
                status_code=400,
                detail="Document has no original document; markdown not available."
            )
        print(f"og_doc_id: {og_doc_id}")
        markdown_service = MarkdownService()
        md_download_url = markdown_service.get_markdown_download_url(og_doc_id)
        json_download_url = markdown_service.get_json_download_url(og_doc_id)
        return {
            "message": "Markdown download URL generated",
            "document_id": doc_id,
            "md_download_url": md_download_url,
            "json_download_url": json_download_url,
            "status_code": 200,
            "success": True
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating markdown download URL: {str(e)}")
