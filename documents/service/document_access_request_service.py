from sqlalchemy.orm import Session
from fastapi import Request, HTTPException
from documents.data.repository import DocumentAccessRepository, DocumentAccessRequestRepository, DocumentRepository
from documents.data.model import DocumentAccessRequest
from documents.service.document_access_service import DocumentAccessService
from users.data.repository import UserRepository
import ulid
import datetime


class DocumentAccessRequestService:
    def __init__(self, db: Session, request: Request):
        self.db = db
        self.repo = DocumentAccessRequestRepository(db)
        self.access_repo = DocumentAccessRepository(db)
        self.doc_repo = DocumentRepository(db)
        self.user_repo = UserRepository(db)
        self.request = request

    def create_access_request(self, document_id: str, message):
        user_id = self.request.state.user_id

        document = self.doc_repo.get_document_by_id(document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")

        if document.owner_id == user_id:
            raise HTTPException(status_code=403, detail="You already own this document")

        existing_access = self.access_repo.get_access_for_user_document(user_id, document_id)
        if existing_access:
            raise HTTPException(status_code=409, detail="You already have access to this document")

        existing_request = self.repo.get_request_by_requester_and_document(user_id, document_id)
        if existing_request:
            raise HTTPException(status_code=409, detail="A pending request already exists for this document")

        req = DocumentAccessRequest(
            request_id="areq_" + str(ulid.new()),
            requester_id=user_id,
            document_id=document_id,
            owner_id=document.owner_id,
            created_at=datetime.datetime.now(),
        )
        return self.repo.create_request(req)

    def get_pending_requests(self):
        from documents.data.schema import AccessRequestInfo, PendingRequestsResponse
        user_id = self.request.state.user_id

        incoming_records = self.repo.get_incoming_requests(user_id)
        outgoing_records = self.repo.get_outgoing_requests(user_id)

        def _enrich(records):
            result = []
            for rec in records:
                requester = self.user_repo.get_user_by_id(rec.requester_id)
                document = self.doc_repo.get_document_by_id(rec.document_id)
                if not requester or not document:
                    continue
                result.append(AccessRequestInfo(
                    request_id=rec.request_id,
                    requester_id=rec.requester_id,
                    document_id=rec.document_id,
                    owner_id=rec.owner_id,
                    created_at=rec.created_at,
                    requester_first_name=requester.first_name,
                    requester_last_name=requester.last_name,
                    requester_email=requester.email_id,
                    document_display_name=document.display_name,
                ))
            return result

        return PendingRequestsResponse(
            incoming=_enrich(incoming_records),
            outgoing=_enrich(outgoing_records),
        )

    def resolve_request(self, request_id: str, accept: bool):
        user_id = self.request.state.user_id

        req = self.repo.get_request_by_id(request_id)
        if not req:
            raise HTTPException(status_code=404, detail="Access request not found")

        if user_id not in (req.owner_id, req.requester_id):
            raise HTTPException(status_code=403, detail="Not authorized to resolve this request")

        if accept:
            if user_id != req.owner_id:
                raise HTTPException(status_code=403, detail="Only the document owner can accept requests")
            access_svc = DocumentAccessService(self.db, self.request)
            access_svc.share_document(req.document_id, [req.requester_id])

        self.repo.delete_request(req)

    def cancel_request(self, request_id: str):
        user_id = self.request.state.user_id

        req = self.repo.get_request_by_id(request_id)
        if not req:
            raise HTTPException(status_code=404, detail="Access request not found")

        if req.requester_id != user_id:
            raise HTTPException(status_code=403, detail="Only the requester can cancel this request")

        self.repo.delete_request(req)
