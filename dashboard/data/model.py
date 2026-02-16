from core.db_client import Base
from sqlalchemy import Column, String, Float, DateTime, JSON, Integer, Boolean
import datetime


class EvalRecord(Base):
    __tablename__ = "eval_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(String, nullable=False, index=True)
    user_email = Column(String, nullable=True, index=True)
    user_query = Column(String, nullable=True)
    faithfulness = Column(Float, nullable=True)
    response_relevancy = Column(Float, nullable=True)
    node_costs = Column(JSON, nullable=True)
    total_cost = Column(Float, nullable=True)
    eval_cost = Column(Float, nullable=True)
    latency_ms = Column(Float, nullable=True)
    is_rag_retrieved = Column(Boolean, nullable=True, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
