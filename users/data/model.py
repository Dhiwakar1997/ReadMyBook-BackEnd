import datetime
from core.db_client import Base
from sqlalchemy import Column, Integer, String, Boolean, DateTime

class User(Base):
    __tablename__ = "users"

    user_id = Column[str](String, primary_key=True, index=True, unique=True)
    first_name = Column[str](String)
    last_name = Column[str](String, nullable=True)
    date_of_birth = Column[DateTime](DateTime, nullable=True)
    gender = Column[str](String, nullable=True)
    email_id = Column[str](String, unique=True, index=True)
    password = Column[str](String, nullable=True)  # Nullable for OAuth users
    
    # OAuth provider fields
    auth_provider = Column[str](String, nullable=True)  # e.g., "google", "email"
    provider_id = Column[str](String, nullable=True)  # OAuth provider's user ID (e.g., Google sub)

    created_at = Column[DateTime](DateTime, default=datetime.datetime.now)
    updated_at = Column[DateTime](DateTime, default=datetime.datetime.now)
    deleted_at = Column[DateTime](DateTime, nullable=True)

    is_deleted = Column[bool](Boolean, default=False)
    is_active = Column[bool](Boolean, default=True)
    is_verified = Column[bool](Boolean, default=False)
    
    verification_code = Column[str](String, nullable=True)
    verification_code_expires_at = Column[DateTime](DateTime, nullable=True)
    pwd_reset_code = Column[str](String, nullable=True)
    pwd_reset_code_expires_at = Column[DateTime](DateTime, nullable=True)
