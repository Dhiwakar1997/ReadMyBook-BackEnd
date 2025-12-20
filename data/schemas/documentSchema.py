from pydantic import BaseModel

class Document(BaseModel):
    document_id: str
    display_name: str
    size_in_kilobyes: float
    document_url: str
    created_at: str
    updated_at: str
    deleted_at: str
    is_deleted: bool
    owner_id: str
    images: list[str]
    is_markdown_extracted: bool

    class config:
        from_attributes = True


class CreateDocumentRequest(Document):
    pdf_url: str
    owner_id: str

class UpdateDocumentRequest(Document):
    document: Document



class UpdateDocumentResponse(BaseModel):
    message: str
    
class AllDocumentsResponse(BaseModel):
    document_dict: dict[str, Document]

class DocumentResponse(BaseModel):
    document: Document

class UpdateDocumentResponse(BaseModel):
    message: str

