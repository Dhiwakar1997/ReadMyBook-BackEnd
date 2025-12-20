from fastapi import APIRouter

image_router = APIRouter(prefix="/documents/{document_id}/images", tags=["images"])

@image_router.get("/")
def get_all_images(document_id: str):
    return {"message": "All images"}

@image_router.get("/{image_id}")
def get_image_by_id(document_id: str, image_id: str):
    return {"message": "Image by id"}
