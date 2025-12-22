from data.models.authModel import AuthModel
from sqlalchemy.orm import Session

class AuthRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_auth_by_document_id(self, document_id: str):
        return self.db.query(AuthModel).filter(AuthModel.document_id == document_id).all()
    
    def get_auth_by_user_id(self, user_id: str):
        return self.db.query(AuthModel).filter(AuthModel.user_id == user_id).all()
    
    def create_auth(self, auth: AuthModel):
        self.db.add(auth)   
        self.db.commit()
        self.db.refresh(auth)
        return auth
    
    def update_auth(self, auth: AuthModel):
        self.db.add(auth)
        self.db.commit()
        self.db.refresh(auth)
        return auth
    
    def delete_auth(self, auth: AuthModel):
        self.db.delete(auth)
        self.db.commit()
        return True