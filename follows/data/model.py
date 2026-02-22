from core.db_client import Base
from sqlalchemy import Column, String, DateTime, ForeignKey, UniqueConstraint
import datetime


class Follow(Base):
    __tablename__ = "follows"

    id = Column(String, primary_key=True, index=True)
    follower_id = Column(String, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    following_id = Column(String, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("follower_id", "following_id", name="uq_follower_following"),
    )
