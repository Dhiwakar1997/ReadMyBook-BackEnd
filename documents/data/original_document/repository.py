from sqlalchemy.orm import Session

from documents.data.original_document.model import OriginalDocument


class OriginalDocumentRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_hash(self, file_hash: str) -> OriginalDocument | None:
        return self.db.query(OriginalDocument).filter(OriginalDocument.file_hash == file_hash).first()

    def get_by_id(self, og_doc_id: str) -> OriginalDocument | None:
        return self.db.query(OriginalDocument).filter(OriginalDocument.original_document_id == og_doc_id).first()

    def create(self, og_doc: OriginalDocument) -> OriginalDocument:
        self.db.add(og_doc)
        self.db.commit()
        self.db.refresh(og_doc)
        return og_doc

    def increment_reference_counter(self, og_doc_id: str) -> OriginalDocument | None:
        og = self.get_by_id(og_doc_id)
        if not og:
            return None
        og.reference_counter = (og.reference_counter or 0) + 1
        self.db.commit()
        self.db.refresh(og)
        return og

    def decrement_reference_counter(self, og_doc_id: str) -> int | None:
        """Decrement reference_counter for the original document. Returns new count, or None if not found."""
        og = self.get_by_id(og_doc_id)
        if not og:
            return None
        current = og.reference_counter or 0
        new_count = max(0, current - 1)
        og.reference_counter = new_count
        self.db.commit()
        self.db.refresh(og)
        return new_count

    def delete_by_id(self, og_doc_id: str) -> bool:
        """Delete the original document row. Returns True if deleted."""
        og = self.get_by_id(og_doc_id)
        if not og:
            return False
        self.db.delete(og)
        self.db.commit()
        return True
