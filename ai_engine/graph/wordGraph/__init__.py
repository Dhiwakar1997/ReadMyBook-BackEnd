"""
Word explanation graph package.
Exposes wordGraph, get_ai_word_explanation, stream_ai_word_explanation.
"""
import re
from typing import AsyncGenerator

from fastapi import Request

from documents.data.schema import ExplainWordDocumentRequest

from ai_engine.graph.stream_utils import sse_event

from .word_state import create_word_explain_state
from .word_graph import wordGraph

__all__ = [
    "wordGraph",
    "get_ai_word_explanation",
    "stream_ai_word_explanation",
]


async def get_ai_word_explanation(
    document_id: str,
    request: Request,
    request_model: ExplainWordDocumentRequest,
) -> dict:
    state = create_word_explain_state(
        document_id=document_id,
        request=request,
        request_model=request_model,
    )
    result = await wordGraph.ainvoke(state)
    return result


async def stream_ai_word_explanation(
    document_id: str,
    request: Request,
    request_model: ExplainWordDocumentRequest,
) -> AsyncGenerator[str, None]:
    state = create_word_explain_state(
        document_id=document_id,
        request=request,
        request_model=request_model,
    )
    final_state: dict = {}
    node_status_map = {
        "rag_retriever": "Retrieving context...",
        "word_explanation_agent": "Generating explanation...",
    }
    rag_was_used = False
    no_rag_buffer = ""
    current_sentence = ""

    async for event in wordGraph.astream_events(state, version="v2"):
        event_kind = event["event"]
        node = event.get("metadata", {}).get("langgraph_node", "")
        tags = event.get("tags", [])

        if event_kind == "on_chain_start" and node in node_status_map:
            yield sse_event("status", {"message": node_status_map[node]})
            if node == "rag_retriever":
                rag_was_used = True
                no_rag_buffer = ""

        elif event_kind == "on_chat_model_stream" and node == "word_explanation_agent":
            if "streaming_response" in tags:
                chunk = event["data"].get("chunk")
                if chunk and chunk.content:
                    if rag_was_used:
                        current_sentence += chunk.content
                        if re.search(r"\.\s", current_sentence):
                            yield sse_event("token", {"content": current_sentence})
                            current_sentence = ""
                    else:
                        no_rag_buffer += chunk.content

        elif event_kind == "on_chain_end" and node == "word_explanation_agent":
            if not rag_was_used:
                output = event["data"].get("output", {})
                if isinstance(output, dict) and not output.get("is_refusal", False):
                    yield sse_event("token", {"content": no_rag_buffer})
                    no_rag_buffer = ""

        elif event_kind == "on_chain_end" and (
            event.get("name") == "LangGraph" or node == ""
        ):
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

    yield sse_event("done", {"reference_contents": reference_contents})
    yield sse_event("_internal_state", {
        "rag_context": final_state.get("rag_context"),
        "is_refusal": final_state.get("is_refusal"),
        "word_to_explain": final_state.get("word_to_explain"),
        "node_costs": final_state.get("node_costs", []),
    })
