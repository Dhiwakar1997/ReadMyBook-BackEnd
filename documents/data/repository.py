from documents.data.model import Document, DocumentAccessModel, DocumentBatch
from sqlalchemy.orm import Session
import uuid

class DocumentRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_all_documents(self, owner_id: str):
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
        document = self.get_document_by_id(document_id)
        if document:
            existing = document.images or []
            document.images = existing + image_names
            self.db.commit()
            return document
        return None


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


class DocumentBatchRepository:
    def __init__(self, db: Session):
        self.db = db
    
    def create_document_batch(self, document_id: str, batch_number: int, status: str, blob_path: str = None):
        batch_id = str(uuid.uuid4())
        document_batch = DocumentBatch(
            batch_id=batch_id,
            document_id=document_id,
            batch_number=batch_number,
            blob_path=blob_path,
            status=status
        )
        self.db.add(document_batch)
        self.db.commit()
        return document_batch
    
    def get_document_batch(self, document_id: str, batch_number: int):
        return self.db.query(DocumentBatch).filter(
            DocumentBatch.document_id == document_id,
            DocumentBatch.batch_number == batch_number
        ).first()
    
    def get_document_batch_by_blob_path(self, blob_path: str):
        return self.db.query(DocumentBatch).filter(DocumentBatch.blob_path == blob_path).first()
    
    def update_document_batch(self, document_id: str, batch_number: int, status: str):
        document_batch = self.get_document_batch(document_id, batch_number)
        if document_batch:
            document_batch.status = status
            self.db.commit()
            return document_batch
        return None
    
    def update_batch_status_by_blob_path(self, blob_path: str, status: str):
        document_batch = self.get_document_batch_by_blob_path(blob_path)
        if document_batch:
            document_batch.status = status
            self.db.commit()
            return document_batch
        return None
    
    def get_pending_batches_count(self, document_id: str) -> int:
        return self.db.query(DocumentBatch).filter(
            DocumentBatch.document_id == document_id,
            DocumentBatch.status != "completed",
            DocumentBatch.is_deleted == False
        ).count()
    
    def get_all_batches_for_document(self, document_id: str):
        return self.db.query(DocumentBatch).filter(
            DocumentBatch.document_id == document_id,
            DocumentBatch.is_deleted == False
        ).order_by(DocumentBatch.batch_number).all()
