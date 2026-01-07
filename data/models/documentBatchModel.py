import datetime
from sqlalchemy import Column, Integer, String, Boolean, Float, ARRAY, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from data.dbClient import Base

class DocumentBatch(Base):
    __tablename__ = "document_batches"
    batch_id = Column(String, primary_key=True, index=True)
    document_id = Column(String, ForeignKey("documents.document_id", ondelete="CASCADE"), nullable=False)
    batch_number = Column(Integer, nullable=False)
    blob_path = Column(String, nullable=True)  # Path to batch PDF in blob storage
    status = Column(String, nullable=False, default="pending")
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    is_deleted = Column(Boolean, nullable=False, default=False)