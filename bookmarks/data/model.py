from core.db_client import Base
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Integer
import datetime

class Bookmark(Base):
    __tablename__ = "bookmarks"

    bookmark_id = Column[str](String, primary_key=True, unique=True)
    user_id = Column[str](String, ForeignKey("users.user_id"), index=True)
    document_id = Column[str](String, ForeignKey("documents.document_id"), index=True)
    created_at = Column[DateTime](DateTime, default=datetime.datetime.now)
    updated_at = Column[DateTime](DateTime, default=datetime.datetime.now)
    color = Column[str](String)
    content_id = Column[int](Integer)
