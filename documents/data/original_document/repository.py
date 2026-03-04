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
