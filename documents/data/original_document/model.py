from core.db_client import Base
from sqlalchemy import Column, String, Boolean, DateTime, Float, ARRAY
import datetime


class OriginalDocument(Base):
    __tablename__ = "original_documents"

    original_document_id = Column(String, primary_key=True, index=True)
    file_hash = Column(String, nullable=False, unique=True, index=True)
    size_in_kilobytes = Column(Float)
    is_active = Column(Boolean, default=True)
    images = Column(ARRAY(String), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now)
