from core.db_client import Base
from sqlalchemy import Column, String, DateTime, ForeignKey, UniqueConstraint
import datetime


class DocumentAccessRequest(Base):
    __tablename__ = "document_access_requests"

    request_id = Column(String, primary_key=True, unique=True)
    requester_id = Column(String, ForeignKey("users.user_id", ondelete="CASCADE"), index=True)
    document_id = Column(String, ForeignKey("documents.document_id", ondelete="CASCADE"), index=True)
    owner_id = Column(String, ForeignKey("users.user_id", ondelete="CASCADE"), index=True)
    created_at = Column(DateTime, default=datetime.datetime.now)

    __table_args__ = (
        UniqueConstraint("requester_id", "document_id", name="uq_access_request_requester_document"),
    )
