"""
Consumes ai-operations events and deducts LLM costs from user balances.

Replaces background thread billing deduction in document_service.py.
Separate from eval_worker so billing succeeds even if eval fails.

Usage:
    python -m workers.billing_worker
"""

import logging

from events.consumer import BaseConsumer
from events.config import CONSUMER_GROUP_BILLING_DEDUCTION
from events.topics import AI_OPERATIONS, AI_OPERATIONS_DLQ
from core.db_client import SessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BillingWorker(BaseConsumer):
    def __init__(self):
        super().__init__(
            group_id=CONSUMER_GROUP_BILLING_DEDUCTION,
            topics=[AI_OPERATIONS],
            dlq_topic=AI_OPERATIONS_DLQ,
            max_retries=5,
        )

    def handle(self, event_type: str, payload: dict) -> None:
        from billing.service.balance_service import BalanceService

        if event_type in ("ask.completed", "explain_word.completed"):
            node_costs = payload.get("node_costs", [])
        elif event_type in ("ask.stream.completed", "explain_word.stream.completed"):
            internal_state = payload.get("internal_state", {})
            node_costs = internal_state.get("node_costs", [])
        else:
            return

        # Determine operation type
        operation = "ask" if event_type.startswith("ask.") else "explain_word"

        # Calculate total cost from node_costs
        total_cost_usd = sum(c.get("cost", 0) for c in node_costs)
        total_tokens = sum(c.get("total_tokens", 0) for c in node_costs)

        if total_cost_usd <= 0:
            return

        user_id = payload.get("user_id")
        doc_id = payload.get("doc_id")

        db = SessionLocal()
        try:
            billing = BalanceService(db)
            billing.deduct_llm_cost(
                user_id=user_id,
                raw_cost_usd=total_cost_usd,
                operation=operation,
                document_id=doc_id,
                token_count=total_tokens,
            )
            logger.info(f"Billing deducted for {event_type} user={user_id}")
        finally:
            db.close()


if __name__ == "__main__":
    BillingWorker().start()
