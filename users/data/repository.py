from users.data.model import User
from sqlalchemy.orm import Session
from sqlalchemy import text

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

    def search_users_with_mutuals(self, query: str, current_user_id: str) -> list[dict]:
        sql = text("""
            SELECT u.user_id, u.first_name, u.last_name,
                (SELECT COUNT(*) FROM follows f1 JOIN follows f2 ON f1.follower_id = f2.follower_id
                 WHERE f1.following_id = :me AND f2.following_id = u.user_id AND f1.follower_id != :me) AS mutual_followers,
                (SELECT COUNT(*) FROM follows f1 JOIN follows f2 ON f1.following_id = f2.following_id
                 WHERE f1.follower_id = :me AND f2.follower_id = u.user_id AND f1.following_id != :me) AS mutual_following
            FROM users u
            WHERE (u.first_name ILIKE :query OR u.email_id ILIKE :query)
              AND u.user_id != :me
              AND u.is_deleted = FALSE
            ORDER BY (
                (SELECT COUNT(*) FROM follows f1 JOIN follows f2 ON f1.follower_id = f2.follower_id
                 WHERE f1.following_id = :me AND f2.following_id = u.user_id AND f1.follower_id != :me) * 2
                +
                (SELECT COUNT(*) FROM follows f1 JOIN follows f2 ON f1.following_id = f2.following_id
                 WHERE f1.follower_id = :me AND f2.follower_id = u.user_id AND f1.following_id != :me)
            ) DESC
            LIMIT 20
        """)
        result = self.db.execute(sql, {"me": current_user_id, "query": f"{query}%"})
        rows = result.fetchall()
        return [
            {
                "user_id": row[0],
                "first_name": row[1],
                "last_name": row[2],
                "mutual_followers": row[3],
                "mutual_following": row[4],
            }
            for row in rows
        ]
