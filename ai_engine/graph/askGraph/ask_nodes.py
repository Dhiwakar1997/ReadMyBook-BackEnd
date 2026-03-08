"""Node functions and router for the ask (RAG chat) graph."""
import time
from typing import Literal

from langchain.chat_models import init_chat_model
from langchain_community.callbacks import get_openai_callback
from langchain_core.messages import SystemMessage, HumanMessage

from ai_engine.prompts import RagRetrievalSystemPrompt, CategoryAwareRagSystemPrompt, QueryRefinerSystemPrompt
from core.utils import get_context_block

from .ask_config import ASK_GRAPH_CONFIG, CATEGORY_AGENT_CONFIG, DEFAULT_CATEGORY_CONFIG
from .ask_models import QueryRefinerResponse, AgentResponse
from .ask_state import State

import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

_llm_cache: dict[tuple[str, float], object] = {}
_refiner_llm = None


def _get_chat_llm(model: str, temperature: float):
    """Get or create a cached LLM instance for the given model/temperature pair."""
    key = (model, temperature)
    if key not in _llm_cache:
        _llm_cache[key] = init_chat_model(model, temperature=temperature)
    return _llm_cache[key]


def _get_refiner_llm():
    global _refiner_llm
    if _refiner_llm is None:
        _refiner_llm = init_chat_model(
            ASK_GRAPH_CONFIG["refiner_model"],
            temperature=ASK_GRAPH_CONFIG["refiner_temperature"],
        )
    return _refiner_llm


def _unclear_query_message(language: str) -> str:
    """Warm, professional rephrase message for unclear queries."""
    return (
        "Thank you for reaching out! It seems like your question might need "
        "a little more context for me to assist you effectively. "
        "Could you try rephrasing it or adding a few more details about "
        "what you'd like to explore? For instance, mentioning a specific topic, "
        "chapter, or concept from the document would help me give you "
        "a much more accurate and helpful response. I'm here to help!"
    )


def _compute_rag_top_k(result: QueryRefinerResponse) -> int:
    """Determine RAG top_k based on query intent signals."""
    if result.requires_deep_analysis:
        return 15
    if result.is_followup:
        return 10
    return 5


def query_refiner(state: State) -> dict:
    t0 = time.perf_counter()
    chat_history = state["request_model"].chat_history or []

    if not chat_history:
        return {"original_query": "", "refined_query": ""}

    refiner_llm = _get_refiner_llm()
    structured_refiner_llm = refiner_llm.with_structured_output(
        QueryRefinerResponse, method="json_schema"
    )
    raw_query = chat_history[-1]["content"]

    if len(chat_history) <= 1:
        with get_openai_callback() as cb:
            result = structured_refiner_llm.invoke([
                SystemMessage(content=QueryRefinerSystemPrompt.format(language="English")),
                HumanMessage(content=f"User's query: {raw_query}"),
            ])
        latency = round((time.perf_counter() - t0) * 1000, 2)
        base = {
            "original_query": raw_query,
            "refined_query": result.refined_query or raw_query,
            "original_query_language": result.user_query_language,
            "chat_summary": "",
            "is_followup": result.is_followup,
            "rag_top_k": _compute_rag_top_k(result),
            "node_costs": [{"node": "query_refiner", "cost": cb.total_cost, "total_tokens": cb.total_tokens, "latency_ms": latency}],
        }
        if result.is_unclear:
            base["ai_response"] = _unclear_query_message(result.user_query_language)
            base["is_refusal"] = True
        return base

    history_text = "\n".join(
        f"{msg['role']}: {msg['content']}" for msg in chat_history[:-1][-6:]
    )
    with get_openai_callback() as cb:
        result = structured_refiner_llm.invoke([
            SystemMessage(content=QueryRefinerSystemPrompt.format(language="English")),
            HumanMessage(content=f"Chat history:\n{history_text}\n\nUser's latest query: {raw_query}"),
        ])
    latency = round((time.perf_counter() - t0) * 1000, 2)
    base = {
        "original_query": raw_query,
        "original_query_language": result.user_query_language,
        "refined_query": result.refined_query or raw_query,
        "chat_summary": result.chat_summary or "",
        "is_followup": result.is_followup,
        "rag_top_k": _compute_rag_top_k(result),
        "node_costs": [{"node": "query_refiner", "cost": cb.total_cost, "total_tokens": cb.total_tokens, "latency_ms": latency}],
    }
    if result.is_unclear:
        base["ai_response"] = _unclear_query_message(result.user_query_language)
        base["is_refusal"] = True
    return base


def query_refiner_router(state: State) -> Literal["__end__", "chat_agent", "rag_retrieval_agent"]:
    """Route based on query analysis: unclear → end, followup → RAG, normal → chat."""
    if state.get("ai_response") is not None:
        return "__end__"
    if state.get("is_followup", False):
        return "rag_retrieval_agent"
    return "chat_agent"


def rag_retrieval_agent(state: State) -> dict:
    t0 = time.perf_counter()
    search_query = state.get("refined_query") or ""
    top_k = state.get("rag_top_k", 5)

    dense_query_vector = state["text_embedding_service"].embed_single_text(search_query)
    bm25_query_vector = state["text_embedding_service"].bm25_embed_texts([search_query])[0]

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
        top_k=top_k,
    )
    context_block = get_context_block(vector_query_results)
    raw_chunks = vector_query_results.get("contexts", [])
    latency = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "rag_context": context_block,
        "retrieval_chunks": raw_chunks if raw_chunks else [context_block],
        "node_costs": [{"node": "rag_retrieval_agent", "cost": 0, "total_tokens": 0, "latency_ms": latency}],
    }


async def chat_agent(state: State) -> dict:
    t0 = time.perf_counter()

    category = state.get("category")
    sub_categories = state.get("sub_categories") or []
    cat_config = CATEGORY_AGENT_CONFIG.get(category, DEFAULT_CATEGORY_CONFIG) if category else DEFAULT_CATEGORY_CONFIG

    llm = _get_chat_llm(cat_config["model"], cat_config["temperature"])
    full_context = state.get("rag_context") or state.get("current_context", "")
    active_context = state.get("active_context", "")
    original_query_language = state.get("original_query_language", "English")
    chat_summary = state.get("chat_summary", "")

    messages = []
    if chat_summary:
        messages.append(SystemMessage(content=f"Conversation summary so far:\n{chat_summary}"))

    if category and category in CATEGORY_AGENT_CONFIG:
        messages.append(SystemMessage(content=CategoryAwareRagSystemPrompt.format(
            persona=cat_config["persona"],
            category=category.replace("_", " ").title(),
            sub_categories=", ".join(s.replace("_", " ").title() for s in sub_categories) or "General",
            style=cat_config["style"],
            full_context=full_context,
            active_context=active_context,
            response_language=original_query_language,
        )))
    else:
        messages.append(SystemMessage(content=RagRetrievalSystemPrompt.format(
            full_context=full_context,
            active_context=active_context,
            response_language=original_query_language,
        )))
    messages.append(HumanMessage(content=state.get("refined_query") or state.get("original_query", "")))

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
                    "Now populate the structured output fields "
                    "(reference_contents, response_language, is_refusal) "
                    "based on this answer."
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
        "node_costs": [{"node": "chat_agent", "cost": total_cost, "total_tokens": total_tokens, "latency_ms": latency}],
    }


def chat_callback_router(state: State) -> Literal["__end__", "rag_retrieval_agent"]:
    if state.get("is_refusal", False) and state.get("rag_context") is None:
        return "rag_retrieval_agent"
    return "__end__"
