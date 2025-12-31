from data.models.documentAccessModel import DocumentAccessModel
from sqlalchemy.orm import Session

class DocumentAccessRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_document_access_by_document_id(self, document_id: str):
        return self.db.query(DocumentAccessModel).filter(DocumentAccessModel.document_id == document_id).all()
    
    def get_document_access_by_user_id(self, user_id: str):
        return self.db.query(DocumentAccessModel).filter(DocumentAccessModel.user_id == user_id).all()
    
    def create_document_access(self, document_access: DocumentAccessModel):
        self.db.add(document_access)   
        self.db.commit()
        self.db.refresh(document_access)
        return document_access
    
    def update_document_access(self, document_access: DocumentAccessModel):
        self.db.add(document_access)
        self.db.commit()
        self.db.refresh(document_access)
        return document_access
    
    def delete_document_access(self, document_access: DocumentAccessModel):
        self.db.delete(document_access)
        self.db.commit()
        return True

