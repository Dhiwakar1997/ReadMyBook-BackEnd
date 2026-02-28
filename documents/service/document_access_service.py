from sqlalchemy.orm import Session
from fastapi import Request, HTTPException
from documents.data.repository import DocumentAccessRepository
from documents.data.model import DocumentAccessModel
from users.data.repository import UserRepository
from shared.redis import RedisService
import ulid


class DocumentAccessService:
    def __init__(self, db: Session, request: Request):
        self.document_access_repository = DocumentAccessRepository(db)
        self.request = request

    def create_document_access(self, user_id: str, document_id: str):
        document_access = DocumentAccessModel(
            document_access_id="document_access_"+str(ulid.new()),
            user_id=user_id,
            document_id=document_id,
            is_owner=True
        )
        return self.document_access_repository.create_document_access(document_access)

    def get_document_access_by_document_id(self, document_id: str):
        return self.document_access_repository.get_document_access_by_document_id(document_id)

    def get_document_access_by_user_id(self, user_id: str):
        return self.document_access_repository.get_document_access_by_user_id(user_id)

    def share_document(self, document_id: str, user_ids: list[str]):
        shared_with = []
        for uid in user_ids:
            existing = self.document_access_repository.get_access_for_user_document(uid, document_id)
            if existing:
                continue
            access = DocumentAccessModel(
                document_access_id="document_access_" + str(ulid.new()),
                user_id=uid,
                document_id=document_id,
                is_owner=False,
            )
            self.document_access_repository.create_document_access(access)
            shared_with.append(uid)

        redis_service = RedisService()
        for uid in user_ids:
            redis_service.delete_value(f"doc:user:{uid}")

        return shared_with

    def get_shared_users(self, document_id: str):
        shared_records = self.document_access_repository.get_shared_users(document_id)
        user_ids = [record.user_id for record in shared_records]
        if not user_ids:
            return []

        user_repo = UserRepository(self.document_access_repository.db)
        shared_users = []
        for uid in user_ids:
            user = user_repo.get_user_by_id(uid)
            if user:
                shared_users.append({
                    "user_id": user.user_id,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "email_id": user.email_id,
                })
        return shared_users

    def unshare_document(self, document_id: str, user_ids: list[str]):
        owner_access = self.document_access_repository.get_owner_access(
            self.request.state.user_id, document_id
        )
        if not owner_access:
            raise HTTPException(status_code=403, detail="Only document owners can unshare documents")

        count = self.document_access_repository.delete_access_for_users(user_ids, document_id)

        redis_service = RedisService()
        for uid in user_ids:
            redis_service.delete_value(f"doc:user:{uid}")

        return count
