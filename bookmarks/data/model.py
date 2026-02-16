from core.db_client import Base
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Integer
import datetime


class Bookmark(Base):
    __tablename__ = "bookmarks"

    bookmark_id = Column[str](String, primary_key=True, unique=True)
    user_id = Column[str](String, ForeignKey("users.user_id", ondelete="CASCADE"), index=True)
    document_id = Column[str](String, ForeignKey("documents.document_id", ondelete="CASCADE"), index=True)
    color = Column[str](String, nullable=False, default="#FFEB3B")
    content_id = Column[int](Integer, nullable=False)
    is_deleted = Column[bool](Boolean, default=False)
    created_at = Column[DateTime](DateTime, default=datetime.datetime.utcnow)
    updated_at = Column[DateTime](DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
