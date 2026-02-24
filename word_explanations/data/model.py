from core.db_client import Base
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Text
import datetime


class WordExplanation(Base):
    __tablename__ = "word_explanations"

    explanation_id = Column(String, primary_key=True, index=True)
    doc_id = Column(
        String,
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        String,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    word = Column(String, nullable=False)
    content_id = Column(Integer, nullable=False)
    page_id = Column(Integer, nullable=False)
    ai_explanation = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
