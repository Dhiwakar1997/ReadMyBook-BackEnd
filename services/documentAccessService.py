from data.repositories.documentAccessRepository import DocumentAccessRepository
from data.models.documentAccessModel import DocumentAccessModel
from sqlalchemy.orm import Session
from fastapi import Depends, Request

import ulid

class DocumentAccessService:
    def __init__(self, db: Session, request: Request):
        self.document_access_repository = DocumentAccessRepository(db)
        self.request = request

    def create_document_access(self, user_id: str, document_id: str):

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
    
    def update_document_access(self, document_access: DocumentAccessModel):
        return self.document_access_repository.update_document_access(document_access)
    
    def delete_document_access(self, document_access: DocumentAccessModel):
        return self.document_access_repository.delete_document_access(document_access)

