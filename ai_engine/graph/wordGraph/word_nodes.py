"""Node functions and router for the word explanation graph."""
import time
from typing import Literal

from langchain.chat_models import init_chat_model
from langchain_community.callbacks import get_openai_callback
from langchain_core.messages import SystemMessage

from ai_engine.prompts import WordExplainSystemPrompt
from core.utils import get_context_block

from .word_config import WORD_GRAPH_CONFIG
from .word_models import AgentResponse
from .word_state import WordExplainState

_llm = None


def _get_llm():
    global _llm
    if _llm is None:
        _llm = init_chat_model(
            WORD_GRAPH_CONFIG["model"],
            temperature=WORD_GRAPH_CONFIG["temperature"],
            max_tokens=WORD_GRAPH_CONFIG["max_tokens"],
        )
    return _llm


def rag_retriever(state: WordExplainState) -> dict:
    t0 = time.perf_counter()
    dense_query_vector = state["text_embedding_service"].embed_single_text(
        state["request_model"].word_to_explain
    )
    bm25_query_vector = state["text_embedding_service"].bm25_embed_texts(
        [state["request_model"].word_to_explain]
    )[0]
    match_query = (
        {"value": state["original_document_id"]}
        if not state["request_model"].is_global_search
        else {"any": state["request"].state.original_accessible_documents}
    )
    query_filter = {"must": [{"key": "doc_id", "match": match_query}]}
    vector_query_results = state["qdrant_repository"].search(
        dense_query_vector=dense_query_vector,
        bm25_query_vector=bm25_query_vector,
        og_document_mapping=state["request"].state.og_document_mapping,
        query_filter=query_filter,
        top_k=20,
        alpha=0.3,
    )
    context_block = get_context_block(vector_query_results)
    latency = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "rag_context": context_block,
        "node_costs": [{"node": "rag_retriever", "cost": 0, "total_tokens": 0, "latency_ms": latency}],
    }


async def word_explanation_agent(state: WordExplainState) -> dict:
    t0 = time.perf_counter()
    llm = _get_llm()
    full_context = state.get("rag_context") or state.get("current_context", "")
    active_context = state.get("active_context", "")
    word_to_explain = state.get("word_to_explain", "")

    messages = [
        SystemMessage(content=WordExplainSystemPrompt.format(
            full_context=full_context,
            active_context=active_context,
            word_to_explain=word_to_explain,
        )),
    ]
    full_text = ""
    with get_openai_callback() as cb_stream:
        async for chunk in llm.astream(messages, config={"tags": ["streaming_response"]}):
            full_text += chunk.content

    structured_llm = llm.with_structured_output(AgentResponse, method="json_schema")
    with get_openai_callback() as cb_struct:
        result = structured_llm.invoke([
            *messages,
            SystemMessage(
                content=(
                    f"The answer has already been written:\n{full_text}\n\n"
                    "Now populate ONLY the structured output fields "
                    "(reference_contents, is_refusal) based on this answer."
                )
            ),
        ])

    latency = round((time.perf_counter() - t0) * 1000, 2)
    total_cost = cb_stream.total_cost + cb_struct.total_cost
    total_tokens = cb_stream.total_tokens + cb_struct.total_tokens
    return {
        "ai_response": full_text,
        "reference_contents": result.reference_contents,
        "is_refusal": result.is_refusal,
        "node_costs": [{"node": "word_explanation_agent", "cost": total_cost, "total_tokens": total_tokens, "latency_ms": latency}],
    }


def word_callback_router(state: WordExplainState) -> Literal["__end__", "rag_retriever"]:
    if state.get("is_refusal", False) and state.get("rag_context") is None:
        return "rag_retriever"
    return "__end__"
