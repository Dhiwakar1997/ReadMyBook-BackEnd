from ..dbClient import Base
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float,List,ForeignKey

class Document(Base):
    __tablename__ = "documents"

    document_id = Column[str](String, primary_key=True, index=True, unique=True)
    display_name = Column[str](String) 
    size_in_kilobyes = Column[float](Float)
    document_url = Column[str](String)
    created_at = Column[DateTime](DateTime, default=DateTime.now)
    updated_at = Column[DateTime](DateTime, default=DateTime.now)
    deleted_at = Column[DateTime](DateTime, nullable=True)
    is_deleted = Column[bool](Boolean, default=False)
    owner_id = Column[str](String, ForeignKey("users.user_id"))

    images = Column[list[str]](List[str])
    pdf_blob_path = Column[str](String)
    markdown_blob_path = Column[str](String)
    is_markdown_extracted = Column[bool](Boolean, default=False)