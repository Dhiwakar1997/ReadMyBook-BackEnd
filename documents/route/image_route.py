from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from documents.service.image_service import ImageService
from documents.service.document_service import DocumentService
from middleware import document_access_validator
from core.db_client import get_db

image_router = APIRouter(prefix="/documents/{doc_id}/images", tags=["images"])

@image_router.get("", dependencies=[Depends(document_access_validator)])
def get_all_images(doc_id: str, request: Request, db: Session = Depends(get_db)):
    """Get temporary download URLs for all images associated with a document."""
    try:
        document_service = DocumentService(db, request)
        document = document_service.get_document_by_id(doc_id)
        og_doc_id = document.original_document_id
        if not og_doc_id:
            raise HTTPException(
                status_code=400,
                detail="Document has no original document; images not available."
            )

        image_names = document.images if document.images else []

        if not image_names:
            return {
                "message": "No images found for this document",
                "document_id": doc_id,
                "images": {},
                "status_code": 200,
                "success": True
            }

        image_service = ImageService()
        image_urls = image_service.get_images_download_urls(og_doc_id, image_names)

        return {
            "message": "Image download URLs generated",
            "document_id": doc_id,
            "images": image_urls,
            "status_code": 200,
            "success": True
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating image download URLs: {str(e)}")

@image_router.get("/{image_name}", dependencies=[Depends(document_access_validator)])
def get_image_by_name(doc_id: str, image_name: str, request: Request, db: Session = Depends(get_db)):
    """Get a temporary download URL for a specific image."""
    try:
        document_service = DocumentService(db, request)
        document = document_service.get_document_by_id(doc_id)
        og_doc_id = document.original_document_id
        if not og_doc_id:
            raise HTTPException(
                status_code=400,
                detail="Document has no original document; images not available."
            )

        image_service = ImageService()
        download_url = image_service.get_image_download_url(og_doc_id, image_name)
        return {
            "message": "Image download URL generated",
            "document_id": doc_id,
            "image_name": image_name,
            "download_url": download_url,
            "status_code": 200,
            "success": True
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating image download URL: {str(e)}")
