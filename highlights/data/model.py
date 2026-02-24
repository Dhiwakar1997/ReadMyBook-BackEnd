from core.db_client import Base
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Integer
import datetime


class Highlight(Base):
    __tablename__ = "highlights"

    highlight_id = Column[str](String, primary_key=True, unique=True)
    user_id = Column[str](String, ForeignKey("users.user_id", ondelete="CASCADE"), index=True)
    document_id = Column[str](String, ForeignKey("documents.document_id", ondelete="CASCADE"), index=True)
    content_id = Column[int](Integer, nullable=False)
    page_number = Column[int](Integer, nullable=False)
    start_index = Column[int](Integer, nullable=False)
    stop_index = Column[int](Integer, nullable=False)
    highlight_color = Column[str](String, nullable=False, default="#FFEB3B")
    created_at = Column[DateTime](DateTime, default=datetime.datetime.utcnow)
    updated_at = Column[DateTime](DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
