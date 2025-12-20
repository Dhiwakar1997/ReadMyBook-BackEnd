from fastapi import APIRouter
from data.schemas.documentSchema import AllDocumentsResponse
from data.schemas import BaseResponse

document_router = APIRouter( prefix="/documents", tags=["documents"])

@document_router.get("/")
def get_all_documents(response_model: AllDocumentsResponse):
    try:
        documents = get_all_documents()
        return AllDocumentsResponse(documents=documents)
    except Exception as e:
        response_model.message = str(e)
        response_model.status_code = 500
        response_model.success = False
        return response_model

@document_router.get("/{document_id}")
def get_document_by_id(document_id: str):
    return {"message": "Document by id"}

@document_router.post("/")
def create_document():
    return {"message": "Document created"}

@document_router.put("/{document_id}")
def update_document():
    return {"message": "Document updated"}

@document_router.delete("/{document_id}")
def delete_document():
    return {"message": "Document deleted"}