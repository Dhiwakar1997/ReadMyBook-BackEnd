from sqlalchemy.orm import Session

from documents.data.document_access_request.model import DocumentAccessRequest


class DocumentAccessRequestRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_request(self, req: DocumentAccessRequest) -> DocumentAccessRequest:
        self.db.add(req)
        self.db.commit()
        self.db.refresh(req)
        return req

    def get_request_by_id(self, request_id: str) -> DocumentAccessRequest | None:
        return self.db.query(DocumentAccessRequest).filter(
            DocumentAccessRequest.request_id == request_id
        ).first()

    def get_request_by_requester_and_document(self, requester_id: str, document_id: str) -> DocumentAccessRequest | None:
        return self.db.query(DocumentAccessRequest).filter(
            DocumentAccessRequest.requester_id == requester_id,
            DocumentAccessRequest.document_id == document_id
        ).first()

    def get_incoming_requests(self, owner_id: str) -> list[DocumentAccessRequest]:
        return self.db.query(DocumentAccessRequest).filter(
            DocumentAccessRequest.owner_id == owner_id
        ).order_by(DocumentAccessRequest.created_at.desc()).all()

    def get_outgoing_requests(self, requester_id: str) -> list[DocumentAccessRequest]:
        return self.db.query(DocumentAccessRequest).filter(
            DocumentAccessRequest.requester_id == requester_id
        ).order_by(DocumentAccessRequest.created_at.desc()).all()

    def delete_request(self, req: DocumentAccessRequest) -> bool:
        self.db.delete(req)
        self.db.commit()
        return True

    def delete_requests_by_document_id(self, document_id: str) -> int:
        count = self.db.query(DocumentAccessRequest).filter(
            DocumentAccessRequest.document_id == document_id
        ).delete(synchronize_session="fetch")
        self.db.commit()
        return count
