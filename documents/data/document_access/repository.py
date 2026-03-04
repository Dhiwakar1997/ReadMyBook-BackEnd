from sqlalchemy.orm import Session

from documents.data.document_access.model import DocumentAccessModel


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

    def get_owner_access(self, user_id: str, doc_id: str):
        return self.db.query(DocumentAccessModel).filter(
            DocumentAccessModel.user_id == user_id,
            DocumentAccessModel.document_id == doc_id,
            DocumentAccessModel.is_owner == True
        ).first()

    def get_access_for_user_document(self, user_id: str, doc_id: str):
        return self.db.query(DocumentAccessModel).filter(
            DocumentAccessModel.user_id == user_id,
            DocumentAccessModel.document_id == doc_id
        ).first()

    def get_shared_users(self, doc_id: str):
        return self.db.query(DocumentAccessModel).filter(
            DocumentAccessModel.document_id == doc_id,
            DocumentAccessModel.is_owner == False
        ).all()

    def delete_access_for_users(self, user_ids: list[str], doc_id: str) -> int:
        count = self.db.query(DocumentAccessModel).filter(
            DocumentAccessModel.user_id.in_(user_ids),
            DocumentAccessModel.document_id == doc_id,
            DocumentAccessModel.is_owner == False
        ).delete(synchronize_session="fetch")
        self.db.commit()
        return count

    def delete_all_by_document_id(self, document_id: str) -> int:
        count = self.db.query(DocumentAccessModel).filter(
            DocumentAccessModel.document_id == document_id
        ).delete(synchronize_session="fetch")
        self.db.commit()
        return count

    def update_og_doc_id_for_document(self, document_id: str, original_document_id: str) -> int:
        count = self.db.query(DocumentAccessModel).filter(
            DocumentAccessModel.document_id == document_id
        ).update({"original_document_id": original_document_id}, synchronize_session="fetch")
        self.db.commit()
        return count
