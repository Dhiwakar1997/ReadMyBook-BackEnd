from ..dbClient import Base
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float,ForeignKey,ARRAY
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
    is_markdown_extracted = Column[bool](Boolean, default=False)