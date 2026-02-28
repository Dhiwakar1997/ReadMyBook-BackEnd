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

class AskDocumentRequest(BaseModel):
    current_context: Optional[str] = "" 
    active_context:  Optional[str] = ""
    chat_history: list[dict] = []
    is_global_search: Optional[bool] = False
    is_external_search: Optional[bool] = False
    is_only_document_search: Optional[bool] = False

class ExplainWordDocumentRequest(BaseModel):
    current_context: Optional[str] = ""
    active_context: Optional[str] = ""
    word_to_explain: str
    content_id: int
    page_id: int
    is_global_search: Optional[bool] = False
    is_external_search: Optional[bool] = False
    is_only_document_search: Optional[bool] = False

class DocumentResponse(BaseModel):
    document: Document

class UpdateDocumentResponse(BaseModel):
    message: str

class ShareDocumentRequest(BaseModel):
    user_ids: list[str]

class ShareDocumentResponse(BaseModel):
    message: str
    success: bool
    status_code: int
    shared_with: list[str]

class SharedUserInfo(BaseModel):
    user_id: str
    first_name: str
    last_name: Optional[str] = None
    email_id: str

class GetSharedUsersResponse(BaseModel):
    shared_users: list[SharedUserInfo]


class DocumentSearchResponse(BaseModel):
    results: list[Document]


class CreateAccessRequestRequest(BaseModel):
    message: Optional[str] = None


class AccessRequestInfo(BaseModel):
    request_id: str
    requester_id: str
    document_id: str
    owner_id: str
    created_at: datetime
    requester_first_name: str
    requester_last_name: Optional[str]
    requester_email: str
    document_display_name: str


class PendingRequestsResponse(BaseModel):
    incoming: list[AccessRequestInfo]
    outgoing: list[AccessRequestInfo]
