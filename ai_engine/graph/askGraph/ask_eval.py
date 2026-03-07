"""Evaluation node and config for the ask graph (DeepEval metrics)."""
import random
import time

from langchain_community.callbacks import get_openai_callback
from deepeval.test_case import LLMTestCase
from deepeval.metrics import FaithfulnessMetric, AnswerRelevancyMetric

from .ask_config import ASK_GRAPH_CONFIG
from .ask_state import State

EVAL_MODEL = ASK_GRAPH_CONFIG["eval_model"]
EVAL_THRESHOLD = ASK_GRAPH_CONFIG["eval_threshold"]
EVAL_SAMPLE_RATE = ASK_GRAPH_CONFIG["eval_sample_rate"]


def eval_node(state: State) -> dict:
    t0 = time.perf_counter()
    user_input = state.get("original_query") or state.get("refined_query") or ""
    response = state.get("ai_response") or ""
    prev_costs = state.get("node_costs", [])

    chunks = state.get("retrieval_chunks")
    if not chunks:
        fallback = state.get("current_context", "")
        chunks = [fallback] if fallback else []

    if state.get("is_refusal"):
        total = sum(c["cost"] for c in prev_costs)
        latency = round((time.perf_counter() - t0) * 1000, 2)
        return {
            "evaluation": {"faithfulness": 0.0, "response_relevancy": 0.0, "refusal_detected": True, "metrics_sampled": False},
            "node_costs": [{"node": "eval_node", "cost": 0, "total_tokens": 0, "latency_ms": latency}],
            "total_cost": total,
        }

    run_metrics = random.random() < EVAL_SAMPLE_RATE and user_input and response
    if not run_metrics:
        total = sum(c["cost"] for c in prev_costs)
        latency = round((time.perf_counter() - t0) * 1000, 2)
        return {
            "evaluation": {"faithfulness": None, "response_relevancy": None, "metrics_sampled": False},
            "node_costs": [{"node": "eval_node", "cost": 0, "total_tokens": 0, "latency_ms": latency}],
            "total_cost": total,
        }

    test_case = LLMTestCase(
        input=user_input,
        retrieval_context=chunks,
        actual_output=response,
    )
    try:
        fm = FaithfulnessMetric(model=EVAL_MODEL, threshold=EVAL_THRESHOLD, async_mode=False)
        rm = AnswerRelevancyMetric(model=EVAL_MODEL, threshold=EVAL_THRESHOLD, async_mode=False)
        with get_openai_callback() as cb:
            fm.measure(test_case)
            rm.measure(test_case)
        faithfulness_score = fm.score
        relevancy_score = rm.score
        if len(fm.verdicts) == 0 and faithfulness_score == 1.0:
            faithfulness_score = None
        eval_cost = cb.total_cost
        eval_tokens = cb.total_tokens
    except Exception as e:
        total = sum(c["cost"] for c in prev_costs)
        latency = round((time.perf_counter() - t0) * 1000, 2)
        return {
            "evaluation": {"faithfulness": None, "response_relevancy": None, "error": str(e), "metrics_sampled": True},
            "node_costs": [{"node": "eval_node", "cost": 0, "total_tokens": 0, "latency_ms": latency}],
            "total_cost": total,
        }

    total = sum(c["cost"] for c in prev_costs) + eval_cost
    latency = round((time.perf_counter() - t0) * 1000, 2)
    evaluation = {
        "faithfulness": round(float(faithfulness_score), 4) if faithfulness_score is not None else None,
        "response_relevancy": round(float(relevancy_score), 4) if relevancy_score is not None else None,
        "metrics_sampled": True,
    }
    return {
        "evaluation": evaluation,
        "node_costs": [{"node": "eval_node", "cost": eval_cost, "total_tokens": eval_tokens, "latency_ms": latency}],
        "total_cost": total,
    }
