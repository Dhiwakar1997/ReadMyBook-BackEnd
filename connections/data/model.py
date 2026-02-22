from core.db_client import Base
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSON
import datetime


class ConnectionGroup(Base):
    __tablename__ = "connection_groups"

    connection_id = Column(String, primary_key=True, index=True)
    parent_id = Column(String, nullable=True)
    chunk_count = Column(Integer, nullable=False, default=0)
    title = Column(String, nullable=True)
    description = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)


class DocumentCorpusState(Base):
    __tablename__ = "document_corpus_state"

    id = Column(String, primary_key=True)
    doc_id = Column(
        String,
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    corpus_mean_vector = Column(JSON, nullable=False)
    chunk_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)
