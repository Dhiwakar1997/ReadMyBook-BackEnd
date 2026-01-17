from documents.data.model import Document
from documents.data.repository import DocumentRepository
from documents.data.schema import CreateDocumentRequest, UpdateDocumentRequest, AskDocumentRequest, ExplainDocumentRequest, ExplainWordDocumentRequest
from sqlalchemy.orm import Session
from fastapi import Request, HTTPException
from documents.data.repository import DocumentAccessRepository
from ai_engine.service.ragService import RagService

import ulid
import datetime

class DocumentService:
    def __init__(self, db: Session, request: Request):
        self.document_repository = DocumentRepository(db)
        self.request = request

    def get_all_documents(self):
        all_documents_dict = {}
        all_documents = self.document_repository.get_all_documents(self.request.state.user_id)
        for document in all_documents:
            all_documents_dict[document.document_id] = document
        return all_documents_dict

    def get_document_by_id(self, document_id: str):
        document = self.document_repository.get_document_by_id(document_id=document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        return document

    def create_document(self, document: CreateDocumentRequest):
        document = Document(
            document_id="doc_"+str(ulid.new()),
            display_name=document.display_name,
            size_in_kilobyes=document.size_in_kilobyes,
            owner_id=self.request.state.user_id,
            created_at=datetime.datetime.now(),
            updated_at=datetime.datetime.now(),
            deleted_at=None,
            is_deleted=False,
            is_active=False,
            images=[],
            markdown_parse_time=None,
        )
        created_document = self.document_repository.create_document(document)
        return created_document
    
    def update_document(self, document_id: str, update_document: UpdateDocumentRequest):
        document = self.document_repository.get_document_by_id(document_id=document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        if update_document.display_name:
            document.display_name = update_document.display_name
        if update_document.is_active is not None:
            document.is_active = update_document.is_active
        document.updated_at = datetime.datetime.now()
        updated_document = self.document_repository.update_document(document)
        return updated_document

    def delete_document(self, document_id: str):
        document = self.document_repository.get_document_by_id(document_id=document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        is_deleted = self.document_repository.delete_document(document)
        return is_deleted
    
    def ask_document(self, request: Request, document_id: str, askDocumentRequest: AskDocumentRequest):
        ragService = RagService()    
        try:
            result = ragService.ask_the_rag(askDocumentRequest, document_id, request)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"LLM request failed: {exc}")

        ai_response = result.get("ai_response", "")
        reference_contents = result.get("reference_contents", [])
        return {"ai_response": ai_response.strip(), "reference_contents": reference_contents}

    def explain_text(self, request: Request, document_id: str, explainDocumentRequest: ExplainDocumentRequest):
        text = explainDocumentRequest.text

        return {"answer": text}
    
    def explain_word_text(self, request: Request, document_id: str, explainWordDocumentRequest: ExplainWordDocumentRequest):
        ragService = RagService()

        try:
            result = ragService.getWordExplanation(explainWordDocumentRequest, document_id, request)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"LLM request failed: {exc}")
        
        ai_response = result.get("ai_response", "")
        reference_contents = result.get("reference_contents", [])   

        return {"ai_response": ai_response.strip(), "reference_contents": reference_contents}


class DocumentAccessService:
    def __init__(self, db: Session, request: Request):
        self.document_access_repository = DocumentAccessRepository(db)
        self.request = request

    def create_document_access(self, user_id: str, document_id: str):
        from documents.data.model import DocumentAccessModel
        document_access = DocumentAccessModel(
            document_access_id="document_access_"+str(ulid.new()),
            user_id=user_id,
            document_id=document_id,
            is_owner=True
        )
        return self.document_access_repository.create_document_access(document_access)
    
    def get_document_access_by_document_id(self, document_id: str):
        return self.document_access_repository.get_document_access_by_document_id(document_id)
    
    def get_document_access_by_user_id(self, user_id: str):
        return self.document_access_repository.get_document_access_by_user_id(user_id)
