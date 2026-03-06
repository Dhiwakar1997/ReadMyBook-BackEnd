from core.db_client import Base
from users.data.model import User
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, ForeignKey, ARRAY
import datetime


class Document(Base):
    __tablename__ = "documents"

    document_id = Column[str](String, primary_key=True, index=True, unique=True)
    display_name = Column[str](String)
    size_in_kilobyes = Column[float](Float)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now)
    deleted_at = Column(DateTime, nullable=True)
    status = Column(String, default="new")
    is_deleted = Column[bool](Boolean, default=False)
    owner_id = Column[str](String, ForeignKey("users.user_id", ondelete="CASCADE"))
    original_document_id = Column(String, ForeignKey("original_documents.original_document_id"), nullable=True, index=True)
    images = Column[list[str]](ARRAY(String), nullable=True)
    markdown_parse_time = Column[float](Float, nullable=True)
    total_batches = Column[int](Integer, nullable=True)
    completed_batches = Column[int](Integer, nullable=True, default=0)
    final_job_status = Column[str](String, nullable=True, default="pending")
    generated_title = Column(String, nullable=True)
    category = Column(String, nullable=True)
    sub_categories = Column(ARRAY(String), nullable=True)
