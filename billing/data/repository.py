# billing/data/repository.py
import os
from sqlalchemy.orm import Session
from sqlalchemy import text
from billing.data.model import UserBalance, UsageTransaction, RazorpayTopUp
from shared.redis import RedisService

# TTL for the cached balance in Redis (seconds)
BALANCE_CACHE_TTL = int(os.getenv("BALANCE_CACHE_TTL", "300"))  # 5 minutes default

# Redis key pattern
def _balance_key(user_id: str) -> str:
    return f"billing:balance:{user_id}"


class BalanceRepository:

    def __init__(self, db: Session):
        self.db = db
        self.redis = RedisService()

    # ── Redis helpers ─────────────────────────────────────────────────────────

    def _cache_balance(self, user_id: str, balance: float):
        """Write the current balance to Redis with TTL."""
        try:
            self.redis.set_value(
                _balance_key(user_id),
                {"balance": round(balance, 6)},
                ttl=BALANCE_CACHE_TTL,
            )
        except Exception as e:
            print(f"[billing/redis] Failed to cache balance for {user_id}: {e}")

    def _read_cached_balance(self, user_id: str) -> float | None:
        """
        Read the balance from Redis.
        Returns the float balance if found, or None on cache miss / error.
        """
        try:
            data = self.redis.get_value(_balance_key(user_id))
            if data is not None and isinstance(data, dict):
                return data.get("balance")
        except Exception as e:
            print(f"[billing/redis] Failed to read cached balance for {user_id}: {e}")
        return None

    def _invalidate_cache(self, user_id: str):
        """Delete the cached balance (forces next read to hit DB)."""
        try:
            self.redis.delete_value(_balance_key(user_id))
        except Exception:
            pass

    # ── DB operations ─────────────────────────────────────────────────────────

    def get_or_create(self, user_id: str, currency: str = "INR") -> UserBalance:
        """Return the user's balance row, creating one with 0.0 if it doesn't exist."""
        row = self.db.query(UserBalance).filter(UserBalance.user_id == user_id).first()
        if not row:
            row = UserBalance(user_id=user_id, balance=0.0, currency=currency, lifetime_spent=0.0)
            self.db.add(row)
            self.db.commit()
            self.db.refresh(row)
            self._cache_balance(user_id, 0.0)
        return row

    def get_balance(self, user_id: str) -> float:
        """
        Redis-first balance read.
        1. Check Redis — return immediately if hit.
        2. On miss — query DB, cache the result, return.
        """
        cached = self._read_cached_balance(user_id)
        if cached is not None:
            return cached

        # Cache miss — read from DB and populate cache
        row = self.get_or_create(user_id)
        self._cache_balance(user_id, row.balance)
        return row.balance

    def credit(self, user_id: str, amount: float, currency: str = "INR") -> float:
        """
        Add credit to a user's balance. Returns the new balance.
        Atomic UPSERT in DB → update Redis.
        """
        self.db.execute(
            text("""
                INSERT INTO user_balances (user_id, balance, currency, lifetime_spent, updated_at)
                VALUES (:uid, :amount, :currency, 0, now())
                ON CONFLICT (user_id)
                DO UPDATE SET
                    balance    = user_balances.balance + :amount,
                    updated_at = now()
            """),
            {"uid": user_id, "amount": amount, "currency": currency}
        )
        self.db.commit()

        # Read back the authoritative balance from DB and cache it
        row = self.db.query(UserBalance).filter(UserBalance.user_id == user_id).first()
        new_balance = row.balance if row else amount
        self._cache_balance(user_id, new_balance)
        return new_balance

    def deduct(self, user_id: str, cost: float) -> tuple[bool, float]:
        """
        Deduct cost from balance atomically.
        UPDATE ... WHERE balance >= cost prevents overdraft at the DB level.
        On success → update Redis.
        On failure → refresh Redis from DB (in case it was stale).
        Returns (success, new_balance).
        """
        result = self.db.execute(
            text("""
                UPDATE user_balances
                SET
                    balance        = balance - :cost,
                    lifetime_spent = lifetime_spent + :cost,
                    updated_at     = now()
                WHERE user_id = :uid
                  AND balance >= :cost
                RETURNING balance
            """),
            {"uid": user_id, "cost": cost}
        )
        self.db.commit()
        row = result.fetchone()

        if row:
            new_balance = row[0]
            self._cache_balance(user_id, new_balance)
            return True, new_balance

        # Deduction failed — refresh cache from DB and return current balance
        current = self.get_or_create(user_id).balance
        self._cache_balance(user_id, current)
        return False, current

    # ── Transaction logging ───────────────────────────────────────────────────

    def log_usage(
        self,
        user_id: str,
        operation: str,
        cost: float,
        balance_after: float,
        document_id: str | None = None,
        raw_llm_cost: float | None = None,
        token_count: int | None = None,
        pages: int | None = None,
        currency: str = "INR",
    ) -> UsageTransaction:
        tx = UsageTransaction(
            user_id=user_id,
            operation=operation,
            document_id=document_id,
            cost=cost,
            raw_llm_cost=raw_llm_cost,
            token_count=token_count,
            pages=pages,
            balance_after=balance_after,
            currency=currency,
        )
        self.db.add(tx)
        self.db.commit()
        return tx

    def log_topup(
        self,
        user_id: str,
        order_id: str,
        payment_id: str,
        amount: float,
        amount_paise: int,
        balance_after: float,
        currency: str = "INR",
    ) -> RazorpayTopUp:
        topup = RazorpayTopUp(
            user_id=user_id,
            razorpay_order_id=order_id,
            razorpay_payment_id=payment_id,
            amount=amount,
            amount_paise=amount_paise,
            balance_after=balance_after,
            status="captured",
            currency=currency,
        )
        self.db.add(topup)
        self.db.commit()
        return topup

    def payment_already_processed(self, payment_id: str) -> bool:
        """Idempotency guard — has this razorpay_payment_id already been credited?"""
        return self.db.query(RazorpayTopUp).filter(
            RazorpayTopUp.razorpay_payment_id == payment_id
        ).first() is not None
