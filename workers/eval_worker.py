"""
Consumes ai-operations events and runs eval_node() to record faithfulness
and response_relevancy metrics.

Replaces background threads in document_service.py for eval recording.

Usage:
    python -m workers.eval_worker
"""

import logging
import datetime

from events.consumer import BaseConsumer
from events.config import CONSUMER_GROUP_EVAL_RECORDING
from events.topics import AI_OPERATIONS, AI_OPERATIONS_DLQ
from core.db_client import SessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EvalWorker(BaseConsumer):
    def __init__(self):
        super().__init__(
            group_id=CONSUMER_GROUP_EVAL_RECORDING,
            topics=[AI_OPERATIONS],
            dlq_topic=AI_OPERATIONS_DLQ,
            max_retries=5,
        )

    def handle(self, event_type: str, payload: dict) -> None:
        from ai_engine.graph.askGraph import eval_node
        from dashboard.data.model import EvalRecord
        from dashboard.data.repository import EvalRecordRepository

        if event_type in ("ask.completed", "explain_word.completed"):
            mock_result = {
                "original_query": payload.get("query", payload.get("word", "")),
                "ai_response": payload.get("ai_response", ""),
                "retrieval_chunks": payload.get("retrieval_chunks", []),
                "current_context": "",
                "is_refusal": payload.get("is_refusal", False),
                "node_costs": payload.get("node_costs", []),
                "rag_context": payload.get("rag_context"),
            }
        elif event_type in ("ask.stream.completed", "explain_word.stream.completed"):
            internal_state = payload.get("internal_state", {})
            mock_result = {
                "original_query": internal_state.get("original_query",
                                                     internal_state.get("word_to_explain",
                                                                        payload.get("query", ""))),
                "ai_response": payload.get("ai_response", ""),
                "retrieval_chunks": internal_state.get("retrieval_chunks", []),
                "current_context": "",
                "is_refusal": payload.get("is_refusal", False),
                "node_costs": internal_state.get("node_costs", []),
                "rag_context": internal_state.get("rag_context"),
            }
        else:
            return

        db = SessionLocal()
        try:
            eval_result = eval_node(mock_result)
            eval_data = eval_result.get("evaluation") or {}
            node_costs = mock_result["node_costs"] + eval_result.get("node_costs", [])

            record = EvalRecord(
                document_id=payload.get("doc_id", ""),
                user_email=payload.get("user_email"),
                user_query=mock_result["original_query"],
                faithfulness=eval_data.get("faithfulness"),
                response_relevancy=eval_data.get("response_relevancy"),
                node_costs=node_costs,
                total_cost=eval_result.get("total_cost"),
                eval_cost=next((c["cost"] for c in node_costs if c["node"] == "eval_node"), 0),
                latency_ms=payload.get("latency_ms", 0),
                is_rag_retrieved=mock_result["rag_context"] is not None,
                created_at=datetime.datetime.utcnow(),
            )
            EvalRecordRepository(db).create(record)
            logger.info(f"Eval recorded for {event_type} doc={payload.get('doc_id')}")
        finally:
            db.close()


if __name__ == "__main__":
    EvalWorker().start()
