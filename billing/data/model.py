# billing/data/model.py
import datetime
from core.db_client import Base
from sqlalchemy import (
    Column, String, Float, DateTime, Integer,
    Index, CheckConstraint
)


class UserBalance(Base):
    """
    One row per user. Stores the current prepaid balance.
    All mutations MUST use atomic UPDATE ... WHERE balance >= cost
    to prevent race conditions under concurrent requests.
    """
    __tablename__ = "user_balances"

    user_id        = Column(String, primary_key=True, index=True)
    balance        = Column(Float, nullable=False, default=0.0)
    currency       = Column(String, nullable=False, default="INR")
    lifetime_spent = Column(Float, nullable=False, default=0.0)
    updated_at     = Column(DateTime, default=datetime.datetime.utcnow,
                            onupdate=datetime.datetime.utcnow)

    __table_args__ = (
        CheckConstraint("balance >= 0", name="balance_non_negative"),
    )


class UsageTransaction(Base):
    """
    Immutable debit log. One row per AI operation.
    Append-only — never update or delete.
    """
    __tablename__ = "usage_transactions"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    user_id       = Column(String, nullable=False, index=True)
    operation     = Column(String, nullable=False)      # "ask" | "explain_word" | "pdf_convert"
    document_id   = Column(String, nullable=True)
    cost          = Column(Float, nullable=False)        # amount deducted (with markup)
    raw_llm_cost  = Column(Float, nullable=True)         # cb.total_cost from OpenAI
    token_count   = Column(Integer, nullable=True)
    pages         = Column(Integer, nullable=True)       # for PDF conversions
    balance_after = Column(Float, nullable=False)
    currency      = Column(String, nullable=False, default="INR")
    created_at    = Column(DateTime, default=datetime.datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_usage_user_created", "user_id", "created_at"),
    )


class RazorpayTopUp(Base):
    """
    Immutable credit log. One row per verified Razorpay payment.
    razorpay_payment_id has a UNIQUE constraint — idempotency guard
    preventing double-credit if the verify endpoint is called twice.
    """
    __tablename__ = "razorpay_topups"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    user_id             = Column(String, nullable=False, index=True)
    razorpay_order_id   = Column(String, nullable=False, index=True)
    razorpay_payment_id = Column(String, nullable=False, unique=True, index=True)
    amount              = Column(Float, nullable=False)      # credited amount
    amount_paise        = Column(Integer, nullable=False)    # raw Razorpay amount (paise)
    currency            = Column(String, nullable=False, default="INR")
    status              = Column(String, nullable=False)     # "captured" | "refunded"
    balance_after       = Column(Float, nullable=False)
    created_at          = Column(DateTime, default=datetime.datetime.utcnow, index=True)
