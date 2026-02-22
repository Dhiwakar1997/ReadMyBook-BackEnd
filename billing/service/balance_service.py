# billing/service/balance_service.py
from billing.data.repository import BalanceRepository
from billing.pricing import MIN_BALANCE, BILLING_CURRENCY
from core.db_client import SessionLocal


class BalanceService:
    """
    High-level billing operations.

    Balance reads go through Redis first (sub-millisecond).
    Balance writes hit DB first (atomic), then immediately update Redis.
    """

    def __init__(self, db=None):
        self._db = db
        self._owns_session = db is None

    @property
    def db(self):
        if self._db is None:
            self._db = SessionLocal()
        return self._db

    def close(self):
        if self._owns_session and self._db:
            self._db.close()

    # ── Read (Redis-first) ────────────────────────────────────────────────────

    def get_balance(self, user_id: str) -> float:
        """Returns the cached balance (Redis) or falls back to DB on miss."""
        return BalanceRepository(self.db).get_balance(user_id)

    def has_sufficient_balance(self, user_id: str) -> bool:
        return self.get_balance(user_id) >= MIN_BALANCE

    # ── Credit (Razorpay top-up verified) ─────────────────────────────────────

    def credit(
        self,
        user_id: str,
        amount: float,
        order_id: str,
        payment_id: str,
        amount_paise: int,
        currency: str = BILLING_CURRENCY,
    ) -> float:
        """
        Credit a user's balance after a verified Razorpay payment.
        Idempotent — returns current balance if payment_id already processed.
        Updates Redis after DB write.
        """
        repo = BalanceRepository(self.db)
        if repo.payment_already_processed(payment_id):
            return repo.get_balance(user_id)

        new_balance = repo.credit(user_id, amount, currency)
        repo.log_topup(
            user_id=user_id,
            order_id=order_id,
            payment_id=payment_id,
            amount=amount,
            amount_paise=amount_paise,
            balance_after=new_balance,
            currency=currency,
        )
        return new_balance

    # ── Deduct (after AI operation completes) ─────────────────────────────────

    def deduct_llm_cost(
        self,
        user_id: str,
        raw_cost_usd: float,
        operation: str,
        document_id: str | None = None,
        token_count: int | None = None,
    ) -> tuple[bool, float]:
        """
        Deduct marked-up LLM cost. Returns (success, balance_after).
        Call AFTER the operation — cost is only known once the LLM call finishes.
        Updates Redis after DB write.
        """
        from billing.pricing import llm_cost
        cost = llm_cost(raw_cost_usd)
        print(cost)
        if cost <= 0:
            return True, self.get_balance(user_id)

        repo = BalanceRepository(self.db)
        success, balance_after = repo.deduct(user_id, cost)
        if success:
            repo.log_usage(
                user_id=user_id,
                operation=operation,
                cost=cost,
                balance_after=balance_after,
                document_id=document_id,
                raw_llm_cost=raw_cost_usd,
                token_count=token_count,
            )
        return success, balance_after

    def deduct_pdf_cost(
        self,
        user_id: str,
        pages: int,
        document_id: str | None = None,
    ) -> tuple[bool, float]:
        """
        Deduct PDF conversion cost. Returns (success, balance_after).
        Updates Redis after DB write.
        """
        from billing.pricing import pdf_cost
        cost = pdf_cost(pages)
        if cost <= 0:
            return True, self.get_balance(user_id)

        repo = BalanceRepository(self.db)
        success, balance_after = repo.deduct(user_id, cost)
        if success:
            repo.log_usage(
                user_id=user_id,
                operation="pdf_convert",
                cost=cost,
                balance_after=balance_after,
                document_id=document_id,
                pages=pages,
            )
        return success, balance_after
