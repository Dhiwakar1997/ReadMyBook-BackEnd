import datetime
from core.db_client import Base
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey


class Notification(Base):
    __tablename__ = "notifications"

    notification_id = Column(String, primary_key=True, index=True, unique=True)
    recipient_id = Column(
        String,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_id = Column(
        String,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    # like | comment | reshare | access_request
    type = Column(String, nullable=False)
    post_id = Column(
        String,
        ForeignKey("posts.post_id", ondelete="CASCADE"),
        nullable=True,
    )
    document_id = Column(String, nullable=True)
    request_id = Column(String, nullable=True)
    message = Column(String, nullable=True)
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
