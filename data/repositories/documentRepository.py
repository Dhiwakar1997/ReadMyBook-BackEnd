from data.models.documentsModel import Document
from sqlalchemy.orm import Session
from fastapi import Request

class DocumentRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_all_documents(self,owner_id: str):
        all_documents = self.db.query(Document).filter(Document.owner_id == owner_id, Document.is_deleted == False).all()
        return all_documents

    def get_document_by_id(self, document_id: str):
        return self.db.query(Document).filter(Document.document_id == document_id).first()

    def create_document(self, document: Document):
        self.db.add(document)
        self.db.commit()
        self.db.refresh(document)
        return document
    
    def update_document(self, document: Document):
        self.db.add(document)
        self.db.commit()
        self.db.refresh(document)
        return document
    
    def delete_document(self, document: Document):
        self.db.delete(document)
        self.db.commit()
        return True