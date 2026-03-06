from core.db_client import Base
from sqlalchemy import Column, String, Boolean, DateTime, Float, ARRAY, Integer
import datetime


class OriginalDocument(Base):
    __tablename__ = "original_documents"

    original_document_id = Column(String, primary_key=True, index=True)
    file_hash = Column(String, nullable=False, unique=True, index=True)
    size_in_kilobytes = Column(Float)
    is_active = Column(Boolean, default=True)
    reference_counter = Column(Integer, default=0, nullable=False)
    images = Column(ARRAY(String), nullable=True)
    generated_title = Column(String, nullable=True)
    summary = Column(String, nullable=True)
    category = Column(String, nullable=True)
    sub_categories = Column(ARRAY(String), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now)
