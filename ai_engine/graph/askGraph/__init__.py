"""
Ask (RAG chat) graph package.
Exposes chatGraph, eval_node, get_ai_chat_response, stream_ai_chat_response, State, create_ask_state.
"""
import re
from typing import AsyncGenerator

from fastapi import Request

from documents.data.schema import AskDocumentRequest

from ai_engine.graph.stream_utils import sse_event

from .ask_state import State, create_ask_state
from .ask_graph import chatGraph
from .ask_eval import eval_node

__all__ = [
    "chatGraph",
    "eval_node",
    "get_ai_chat_response",
    "stream_ai_chat_response",
    "State",
    "create_ask_state",
]


async def get_ai_chat_response(
    document_id: str,
    request: Request,
    request_model: AskDocumentRequest,
) -> dict:
    state = create_ask_state(document_id=document_id, request=request, request_model=request_model)
    result = await chatGraph.ainvoke(state)
    return result


async def stream_ai_chat_response(
    document_id: str,
    request: Request,
    request_model: AskDocumentRequest,
) -> AsyncGenerator[str, None]:
    """Runs the chat graph via astream_events() and yields SSE message strings."""
    state = create_ask_state(document_id=document_id, request=request, request_model=request_model)
    final_state: dict = {}

    node_status_map = {
        "query_refiner": "Refining your query...",
        "rag_retrieval_agent": "Retrieving relevant context...",
        "chat_agent": "Generating response...",
    }
    current_sentence = ""

    async for event in chatGraph.astream_events(state, version="v2"):
        event_kind = event["event"]
        node = event.get("metadata", {}).get("langgraph_node", "")
        tags = event.get("tags", [])

        if event_kind == "on_chain_start" and node in node_status_map:
            if node == "rag_retrieval_agent":
                current_sentence = ""
            yield sse_event("status", {"message": node_status_map[node]})

        elif event_kind == "on_chat_model_stream" and node == "chat_agent":
            if "streaming_response" in tags:
                chunk = event["data"].get("chunk")
                if chunk and chunk.content:
                    current_sentence += chunk.content
                    if re.search(r"(\.\s|,)", current_sentence):
                        yield sse_event("token", {"content": current_sentence})
                        current_sentence = ""

        elif event_kind == "on_chain_end" and (
            event.get("name") == "LangGraph" or node == ""
        ):
            current_sentence = re.sub(
                r"\[(Document id: .+)?SOURCE page .+\| index .+\]",
                "",
                current_sentence,
            )
            if current_sentence:
                yield sse_event("token", {"content": current_sentence})
            output = event["data"].get("output", {})
            if isinstance(output, dict) and "ai_response" in output:
                final_state = output

    reference_contents = []
    for ref in (final_state.get("reference_contents") or []):
        if hasattr(ref, "document_id"):
            reference_contents.append({
                "document_id": ref.document_id,
                "page": ref.page,
                "content_index": ref.content_index,
                "text": ref.text,
            })
        else:
            reference_contents.append(ref)

    yield sse_event("done", {
        "reference_contents": reference_contents,
        "is_refusal": final_state.get("is_refusal", False),
        "response_language": final_state.get("original_query_language", "English"),
    })
    yield sse_event("_internal_state", {
        "node_costs": final_state.get("node_costs", []),
        "retrieval_chunks": final_state.get("retrieval_chunks") or [],
        "original_query": final_state.get("original_query", ""),
        "rag_context": final_state.get("rag_context"),
    })
