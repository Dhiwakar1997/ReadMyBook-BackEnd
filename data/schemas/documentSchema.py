from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class Document(BaseModel):
    document_id: str
    display_name: str
    size_in_kilobyes: float
    document_url: Optional[str]
    created_at: datetime
    updated_at: datetime
    is_deleted: bool
    owner_id: str
    images: Optional[list[str]]
    is_markdown_extracted: bool
    pdf_blob_path: Optional[str]
    markdown_blob_path: Optional[str]

    class Config:
        from_attributes = True


class CreateDocumentRequest(BaseModel):
    display_name: str
    size_in_kilobyes: float
    owner_id: str
    
class AllDocumentsResponse(BaseModel):
    document_dict: dict[str, Document]

class DocumentResponse(BaseModel):
    document: Document

class UpdateDocumentResponse(BaseModel):
    message: str

