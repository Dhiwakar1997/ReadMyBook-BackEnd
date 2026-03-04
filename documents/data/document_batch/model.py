from core.db_client import Base
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey
import datetime


class DocumentBatch(Base):
    __tablename__ = "document_batches"
    batch_id = Column(String, primary_key=True, index=True)
    document_id = Column(String, ForeignKey("documents.document_id", ondelete="CASCADE"), nullable=False)
    batch_number = Column(Integer, nullable=False)
    blob_path = Column(String, nullable=True)
    status = Column(String, nullable=False, default="pending")
    parse_time = Column(Float, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    is_deleted = Column(Boolean, nullable=False, default=False)
