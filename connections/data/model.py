from core.db_client import Base
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON
import datetime


class Connection(Base):
    __tablename__ = "connections"

    connection_id = Column(String, primary_key=True, index=True)
    doc_id = Column(
        String,
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content_id = Column(Integer, nullable=False)
    source_text = Column(Text, nullable=False)
    connected_chunks = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("doc_id", "content_id", name="uq_doc_content"),
    )
