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
    is_active: bool
    owner_id: str
    images: Optional[list[str]]
    markdown_parse_time: Optional[float]

    class Config:
        from_attributes = True


class CreateDocumentRequest(BaseModel):
    display_name: str
    size_in_kilobyes: float
    owner_id: str
    
class AllDocumentsResponse(BaseModel):
    document_dict: dict[str, Document]

class UpdateDocumentRequest(BaseModel):
    display_name: Optional[str] = None
    is_active: Optional[bool] = None

class AskDocumentRequest(BaseModel):
    current_context: Optional[str] = None
    chat_history: list[dict] = []
    is_global_search: Optional[bool] = False
    is_external_search: Optional[bool] = False
    is_only_document_search: Optional[bool] = False

class ExplainDocumentRequest(BaseModel):
    text: str   
    is_global_search: Optional[bool] = False
    is_external_search: Optional[bool] = False
    is_only_document_search: Optional[bool] = False

class ExplainWordDocumentRequest(BaseModel):
    text: str   
    word: str
    is_global_search: Optional[bool] = False
    is_external_search: Optional[bool] = False
    is_only_document_search: Optional[bool] = False

class DocumentResponse(BaseModel):
    document: Document

class UpdateDocumentResponse(BaseModel):
    message: str
