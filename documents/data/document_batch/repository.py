from sqlalchemy.orm import Session
from sqlalchemy import func
import uuid

from documents.data.document_batch.model import DocumentBatch


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

    def update_document_batch(self, document_id: str, batch_number: int, status: str, parse_time: float = None):
        document_batch = self.get_document_batch(document_id, batch_number)
        if document_batch:
            document_batch.status = status
            if parse_time is not None:
                document_batch.parse_time = parse_time
            self.db.commit()
            return document_batch
        return None

    def get_total_parse_time(self, document_id: str) -> float:
        """Sum parse_time across all completed batches for a document."""
        result = self.db.query(func.coalesce(func.sum(DocumentBatch.parse_time), 0.0)).filter(
            DocumentBatch.document_id == document_id,
            DocumentBatch.is_deleted == False
        ).scalar()
        return float(result)

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
