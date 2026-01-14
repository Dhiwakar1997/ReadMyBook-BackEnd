from core.db_client import Base
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, ForeignKey, ARRAY
import datetime

class Document(Base):
    __tablename__ = "documents"

    document_id = Column[str](String, primary_key=True, index=True, unique=True)
    display_name = Column[str](String) 
    size_in_kilobyes = Column[float](Float)
    document_url = Column[str](String, nullable=True)
    created_at = Column[DateTime](DateTime, default=datetime.datetime.now)
    updated_at = Column[DateTime](DateTime, default=datetime.datetime.now)
    deleted_at = Column[DateTime](DateTime, nullable=True)
    is_active = Column[bool](Boolean, default=False)
    is_deleted = Column[bool](Boolean, default=False)
    owner_id = Column[str](String, ForeignKey("users.user_id", ondelete="CASCADE"))
    images = Column[list[str]](ARRAY(String), nullable=True)
    markdown_parse_time = Column[float](Float, nullable=True)
    total_batches = Column[int](Integer, nullable=True)
    completed_batches = Column[int](Integer, nullable=True, default=0)
    final_job_status = Column[str](String, nullable=True, default="pending")


class DocumentAccessModel(Base):
    __tablename__ = "document_access"

    document_access_id = Column[str](String, primary_key=True, unique=True)
    user_id = Column[str](String, ForeignKey("users.user_id", ondelete="CASCADE"), index=True)
    document_id = Column[str](String, ForeignKey("documents.document_id", ondelete="CASCADE"), index=True)
    is_owner = Column[bool](Boolean, default=False)
    created_at = Column[DateTime](DateTime, default=datetime.datetime.now)


class DocumentBatch(Base):
    __tablename__ = "document_batches"
    batch_id = Column(String, primary_key=True, index=True)
    document_id = Column(String, ForeignKey("documents.document_id", ondelete="CASCADE"), nullable=False)
    batch_number = Column(Integer, nullable=False)
    blob_path = Column(String, nullable=True)
    status = Column(String, nullable=False, default="pending")
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    is_deleted = Column(Boolean, nullable=False, default=False)
