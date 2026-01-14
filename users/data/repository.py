from users.data.model import User
from sqlalchemy.orm import Session

class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_user(self, user: User):
        try:
            self.db.add(user)
            self.db.commit()
            self.db.refresh(user)
            return user
        except Exception as e:
            self.db.rollback()
            raise e
        finally:
            self.db.close()

    def get_user_by_email_id(self, email_id: str):
        return self.db.query(User).filter(User.email_id == email_id).first()
    
    def get_user_by_id(self, user_id: str):
        return self.db.query(User).filter(User.user_id == user_id).first()
    
    def get_user_by_provider_id(self, provider_id: str, auth_provider: str):
        """Get user by OAuth provider ID and provider name (e.g., Google sub)."""
        return self.db.query(User).filter(
            User.provider_id == provider_id,
            User.auth_provider == auth_provider
        ).first()
    
    def update_user(self, user: User):
        self.db.commit()
        self.db.refresh(user)
        return user
    
    def delete_user(self, user_id: str):
        user = self.db.query(User).filter(User.user_id == user_id).first()
        if not user:
            return None
        self.db.delete(user)
        self.db.commit()
        return user
