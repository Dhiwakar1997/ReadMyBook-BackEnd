# billing/service/balance_service.py
from billing.data.repository import BalanceRepository

from billing.pricing import llm_cost, MARKUP, USD_TO_INR, PDF_CONVERSION_MARKUP,conversion_time_cost,  MIN_BALANCE, BILLING_CURRENCY
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

    def _safe_log_usage(self, repo: BalanceRepository, **kwargs):
        """Log usage transaction, swallowing errors so a failed log doesn't
        mask a successful balance deduction."""
        try:
            repo.log_usage(**kwargs)
        except Exception as e:
            print(f"[billing] Failed to log usage transaction: {e}")

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

        original_cost = round(raw_cost_usd * USD_TO_INR, 4)
        total_cost = llm_cost(raw_cost_usd)
        if total_cost <= 0:
            return True, self.get_balance(user_id)

        repo = BalanceRepository(self.db)
        success, balance_after = repo.deduct(user_id, total_cost)
        if success:
            self._safe_log_usage(
                repo,
                user_id=user_id,
                consumption_type="ai",
                operation=operation,
                total_cost=total_cost,
                balance_after=balance_after,
                original_cost=original_cost,
                markup=MARKUP,
                document_id=document_id,
                raw_llm_cost=raw_cost_usd,
                token_count=token_count,
            )
        return success, balance_after

    def deduct_conversion_time_cost(
        self,
        user_id: str,
        total_seconds: float,
        document_id: str | None = None,
    ) -> tuple[bool, float]:
        """
        Deduct conversion cost based on total seconds taken (+ 15s node start).
        Rate: ₹0.0110152 per second. Returns (success, balance_after).
        """

        original_total_cost = conversion_time_cost(total_seconds)
        if original_total_cost <= 0:
            return True, self.get_balance(user_id)

        repo = BalanceRepository(self.db)
        total_cost = original_total_cost *  PDF_CONVERSION_MARKUP
        success, balance_after = repo.deduct(user_id, total_cost)
        if success:
            self._safe_log_usage(
                repo,
                user_id=user_id,
                consumption_type="conversion",
                operation="md_convert",
                total_cost=total_cost,
                balance_after=balance_after,
                original_cost=original_total_cost,
                markup=PDF_CONVERSION_MARKUP,
                document_id=document_id,
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
        total_cost = pdf_cost(pages)
        if total_cost <= 0:
            return True, self.get_balance(user_id)

        repo = BalanceRepository(self.db)
        success, balance_after = repo.deduct(user_id, total_cost)
        if success:
            self._safe_log_usage(
                repo,
                user_id=user_id,
                consumption_type="conversion",
                operation="pdf_convert",
                total_cost=total_cost,
                balance_after=balance_after,
                original_cost=total_cost,
                markup=1.0,
                document_id=document_id,
            )
        return success, balance_after

    def deduct_mathpix_cost(
        self,
        user_id: str,
        pages: int,
        images: int = 0,
        document_id: str | None = None,
    ) -> tuple[bool, float]:
        """
        Deduct Mathpix conversion cost ($0.0035/page + $0.0015/image + node start → INR).
        Returns (success, balance_after). Updates Redis after DB write.
        """
        from billing.pricing import mathpix_cost
        total_cost = mathpix_cost(pages, images)
        if total_cost <= 0:
            return True, self.get_balance(user_id)

        repo = BalanceRepository(self.db)
        success, balance_after = repo.deduct(user_id, total_cost)
        if success:
            self._safe_log_usage(
                repo,
                user_id=user_id,
                consumption_type="conversion",
                operation="mathpix_convert",
                total_cost=total_cost,
                balance_after=balance_after,
                original_cost=total_cost,
                markup=1.0,
                document_id=document_id,
            )
        return success, balance_after
