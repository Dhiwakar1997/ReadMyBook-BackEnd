from data.models.documentsModel import Document
from data.repositories.documentRepository import DocumentRepository
from data.schemas.documentSchema import CreateDocumentRequest, UpdateDocumentRequest
from sqlalchemy.orm import Session
from fastapi import Depends, Request, HTTPException
from data.dbClient import get_db
from services.azureBlobService import AzureBlobService

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
            document_id=str(ulid.new()),
            display_name=document.display_name,
            size_in_kilobyes=document.size_in_kilobyes,
            owner_id=document.owner_id,
            created_at=datetime.datetime.now(),
            updated_at=datetime.datetime.now(),
            deleted_at=None,
            is_deleted=False,
            is_markdown_extracted=False,
            images=[],
            pdf_blob_path=None,
            markdown_blob_path=None,
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