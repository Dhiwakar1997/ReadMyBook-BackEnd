from fastapi import APIRouter

markdown_router = APIRouter( prefix="/documents/{document_id}/markdowns", tags=["markdowns"])

@markdown_router.get("/")
def get_all_markdowns(document_id: str):
    return {"message": "All markdowns"}