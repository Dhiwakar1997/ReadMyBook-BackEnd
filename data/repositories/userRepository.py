from data.models.usersModel import User
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
    
    def update_user(self, user_id: str, user: User):
        self.db.query(User).filter(User.user_id == user_id).update(user)
        self.db.commit()
        return user
    
    def delete_user(self, user: User):
        self.db.delete(user)
        self.db.commit()
        return user