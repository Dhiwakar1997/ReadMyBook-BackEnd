from fastapi import APIRouter, Depends, HTTPException
from services.markdownService import MarkdownService
from middleware import document_access_validator

markdown_router = APIRouter(prefix="/documents/{document_id}/markdowns", tags=["markdowns"])

@markdown_router.get("/", dependencies=[Depends(document_access_validator)])
def get_markdown_download_url(document_id: str):
    """Get a temporary download URL for the markdown file."""
    try:
        markdown_service = MarkdownService()
        download_url = markdown_service.get_markdown_download_url(document_id)
        return {
            "message": "Markdown download URL generated",
            "document_id": document_id,
            "download_url": download_url,
            "status_code": 200,
            "success": True
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating markdown download URL: {str(e)}")