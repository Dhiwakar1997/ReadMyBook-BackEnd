from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from services.imageService import ImageService
from services.documentService import DocumentService
from middleware import document_access_validator
from data.dbClient import get_db

image_router = APIRouter(prefix="/documents/{document_id}/images", tags=["images"])

@image_router.get("", dependencies=[Depends(document_access_validator)])
def get_all_images(document_id: str, request: Request, db: Session = Depends(get_db)):
    """Get temporary download URLs for all images associated with a document."""
    try:
        # Get the document to retrieve the list of images
        document_service = DocumentService(db, request)
        document = document_service.get_document_by_id(document_id)
        
        # Get the list of image names from the document
        image_names = document.images if document.images else []
        
        if not image_names:
            return {
                "message": "No images found for this document",
                "document_id": document_id,
                "images": {},
                "status_code": 200,
                "success": True
            }
        
        # Generate download URLs for all images
        image_service = ImageService()
        image_urls = image_service.get_images_download_urls(document_id, image_names)
        
        return {
            "message": "Image download URLs generated",
            "document_id": document_id,
            "images": image_urls,
            "status_code": 200,
            "success": True
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating image download URLs: {str(e)}")

@image_router.get("/{image_name}", dependencies=[Depends(document_access_validator)])
def get_image_by_name(document_id: str, image_name: str):
    """Get a temporary download URL for a specific image."""
    try:
        image_service = ImageService()
        download_url = image_service.get_image_download_url(document_id, image_name)
        return {
            "message": "Image download URL generated",
            "document_id": document_id,
            "image_name": image_name,
            "download_url": download_url,
            "status_code": 200,
            "success": True
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating image download URL: {str(e)}")
