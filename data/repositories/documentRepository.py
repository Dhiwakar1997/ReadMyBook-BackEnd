from data.models.documentsModel import Document
from sqlalchemy.orm import Session

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
        # Document object is already tracked by the session and modified
        # Just commit the changes - SQLAlchemy will detect and persist them
        self.db.commit()
        self.db.refresh(document)
        return document
    
    def delete_document(self, document: Document):
        self.db.delete(document)
        self.db.commit()
        return True
    
    def set_total_batches(self, document_id: str, total_batches: int):
        document = self.get_document_by_id(document_id)
        if document:
            document.total_batches = total_batches
            document.completed_batches = 0
            self.db.commit()
            return document
        return None
    
    def increment_completed_batches(self, document_id: str):
        document = self.get_document_by_id(document_id)
        if document:
            document.completed_batches = (document.completed_batches or 0) + 1
            self.db.commit()
            return document
        return None
    
    def update_final_job_status(self, document_id: str, status: str):
        document = self.get_document_by_id(document_id)
        if document:
            document.final_job_status = status
            self.db.commit()
            return document
        return None
    
    def is_all_batches_complete(self, document_id: str) -> bool:
        document = self.get_document_by_id(document_id)
        if document and document.total_batches:
            return (document.completed_batches or 0) >= document.total_batches
        return False
    
    def append_images(self, document_id: str, image_names: list[str]):
        """Append image filenames to the document's images array."""
        document = self.get_document_by_id(document_id)
        if document:
            existing = document.images or []
            document.images = existing + image_names
            self.db.commit()
            return document
        return None