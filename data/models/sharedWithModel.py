from ..dbClient import Base
from sqlalchemy import Column, String, Boolean, DateTime,ForeignKey
import datetime

class SharedWith(Base):
    __tablename__ = "shared_with"

    shared_with_id = Column[str](String, primary_key=True, unique=True)
    user_id = Column[str](String, ForeignKey("users.user_id"),index=True)
    document_id = Column[str](String, ForeignKey("documents.document_id"),index=True)
    is_owner = Column[bool](Boolean, default=False)
    created_at = Column[DateTime](DateTime, default=datetime.datetime.now)
