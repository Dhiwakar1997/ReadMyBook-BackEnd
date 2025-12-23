from data.repositories.authRepository import AuthRepository
from data.models.authModel import AuthModel
from sqlalchemy.orm import Session
from fastapi import Depends, Request

import ulid

class AuthService:
    def __init__(self, db: Session, request: Request):
        self.auth_repository = AuthRepository(db)
        self.request = request

    def create_auth(self, user_id: str, document_id: str):

        auth = AuthModel(
            auth_id="auth_"+str(ulid.new()),
            user_id=user_id,
            document_id=document_id,
            is_owner=True
        )
        return self.auth_repository.create_auth(auth)
    
    def get_auth_by_document_id(self, document_id: str):
        return self.auth_repository.get_auth_by_document_id(document_id)
    
    def get_auth_by_user_id(self, user_id: str):
        return self.auth_repository.get_auth_by_user_id(user_id)
    
    def update_auth(self, auth: AuthModel):
        return self.auth_repository.update_auth(auth)
    
    def delete_auth(self, auth: AuthModel):
        return self.auth_repository.delete_auth(auth)