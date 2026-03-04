from ai_engine.data.qdrantRepository import QdrantRepository
from ai_engine.service.textEmbeddingService import TextEmbeddingService
from documents.data.schema import ExplainWordDocumentRequest
from core.utils import get_context_block
from langgraph.graph import StateGraph, START, END
from langchain.chat_models import init_chat_model
from langchain_community.callbacks import get_openai_callback
from pydantic import BaseModel, Field
from typing import Literal, AsyncGenerator, Annotated
import operator
import time
from typing_extensions import TypedDict
from langchain_core.messages import SystemMessage, HumanMessage
from ai_engine.prompts import WordExplainSystemPrompt
from fastapi import Request
import re
import json

llm = init_chat_model("openai:gpt-4.1", temperature=0.2,  max_tokens=250)


class contextTracker(BaseModel):
    document_id: str = Field(
        ...,
        description="The unique identifier of the document from which the context was taken."
    )
    page: int = Field(
        ...,
        description="The source page number from which the context was taken."
    )
    content_index: int = Field(
        ...,
        description="The source index of the content block from which the context was taken."
    )
    text: str = Field(
        ...,
        description="The source actual text content used as context."
    )

class AgentResponse(BaseModel):
    reference_contents: list[contextTracker] = Field(...,
        description="Provide a list of up to five highly relevant context items used to generate the response."
    )
    is_refusal: bool = Field(
        ...,
        description="True if you could not answer the question from the provided context and responded with a refusal or 'I don't know' type answer. False if you provided a substantive informative answer."
    )


class WordExplainState(TypedDict):
    original_document_id: str
    rag_context: str | None
    current_context: str | None
    active_context: str | None
    word_to_explain: str | None
    ai_response: str | None
    reference_contents: list[contextTracker] | None
    is_refusal: bool | None
    node_costs: Annotated[list, operator.add]
    qdrant_repository: QdrantRepository
    text_embedding_service: TextEmbeddingService
    request_model: ExplainWordDocumentRequest
    request: Request


def rag_retriever(state: WordExplainState):
    t0 = time.perf_counter()
    dense_query_vector = state["text_embedding_service"].embed_single_text(state["request_model"].word_to_explain)
    bm25_query_vector = state["text_embedding_service"].bm25_embed_texts([state["request_model"].word_to_explain])[0]

    matchQuery = {"value": state["original_document_id"]} if not state["request_model"].is_global_search else {"any": state["request"].state.original_accessible_documents}

    query_filter = {
        "must": [
            {
                "key": "doc_id",
                "match": matchQuery,
            }
        ]
    }
    vectorQueryResults = state["qdrant_repository"].search(
        dense_query_vector=dense_query_vector,
        bm25_query_vector=bm25_query_vector,
        og_document_mapping=state["request"].state.og_document_mapping,
        query_filter=query_filter,
        top_k=20,
        alpha=0.3,
    )
    context_block = get_context_block(vectorQueryResults)
    latency = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "rag_context": context_block,
        "node_costs": [{"node": "rag_retriever", "cost": 0, "total_tokens": 0, "latency_ms": latency}],
    }


async def word_explanation_agent(state: WordExplainState):
    t0 = time.perf_counter()
    full_context = state.get("rag_context") if state.get("rag_context") else state.get("current_context", "")
    active_context = state.get("active_context", "")
    word_to_explain = state.get("word_to_explain", "")

    messages = [
        SystemMessage(content=WordExplainSystemPrompt.format(
            full_context=full_context,
            active_context=active_context,
            word_to_explain=word_to_explain,
        )),
    ]

    # ── Sub-call 1: stream tokens ─────────────────────────────────────────────
    full_text = ""
    with get_openai_callback() as cb_stream:
        async for chunk in llm.astream(messages, config={"tags": ["streaming_response"]}):
            full_text += chunk.content

    # ── Sub-call 2: structured output for metadata ────────────────────────────
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
            )
        ])

    latency = round((time.perf_counter() - t0) * 1000, 2)
    total_cost   = cb_stream.total_cost   + cb_struct.total_cost
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


graph_builder = StateGraph(WordExplainState)

graph_builder.add_node("rag_retriever", rag_retriever)
graph_builder.add_node("word_explanation_agent", word_explanation_agent)
graph_builder.add_edge(START, "word_explanation_agent")
graph_builder.add_edge("rag_retriever", "word_explanation_agent")
graph_builder.add_conditional_edges("word_explanation_agent", word_callback_router, {
    "__end__": END,
    "rag_retriever": "rag_retriever",
})
wordGraph = graph_builder.compile()


async def get_ai_word_explanation(document_id: str, request: Request, request_model: ExplainWordDocumentRequest) -> dict:
    current_context = f"Document id: {document_id} - {request_model.current_context}"
    state: WordExplainState = {
        "original_document_id": document_id,
        "current_context": current_context,
        "active_context": request_model.active_context,
        "rag_context": None,
        "word_to_explain": request_model.word_to_explain,
        "ai_response": None,
        "reference_contents": None,
        "is_refusal": None,
        "node_costs": [],
        "qdrant_repository": QdrantRepository(),
        "text_embedding_service": TextEmbeddingService(),
        "request_model": request_model,
        "request": request,
    }
    result = await wordGraph.ainvoke(state)
    return result


def _sse_event(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


async def stream_ai_word_explanation(
    document_id: str,
    request: Request,
    request_model: ExplainWordDocumentRequest,
) -> AsyncGenerator[str, None]:
    current_context = f"Document id: {document_id} - {request_model.current_context}"
    state: WordExplainState = {
        "original_document_id": document_id,
        "current_context": current_context,
        "active_context": request_model.active_context,
        "rag_context": None,
        "word_to_explain": request_model.word_to_explain,
        "ai_response": None,
        "reference_contents": None,
        "is_refusal": None,
        "node_costs": [],
        "qdrant_repository": QdrantRepository(),
        "text_embedding_service": TextEmbeddingService(),
        "request_model": request_model,
        "request": request,
    }

    final_state: dict = {}

    node_status_map = {
        "rag_retriever":          "Retrieving context...",
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
            yield _sse_event("status", {"message": node_status_map[node]})
            if node == "rag_retriever":
                rag_was_used = True
                no_rag_buffer = ""  # discard buffered refusal tokens

        elif event_kind == "on_chat_model_stream" and node == "word_explanation_agent":
            if "streaming_response" in tags:
                chunk = event["data"].get("chunk")
                if chunk and chunk.content:
                    if rag_was_used:
                        current_sentence += chunk.content
                        if re.search(r"\.\s", current_sentence):
                            yield _sse_event("token", {"content": current_sentence})
                            current_sentence = ""
                    else:
                        no_rag_buffer += chunk.content

        elif event_kind == "on_chain_end" and node == "word_explanation_agent":
            if not rag_was_used:
                output = event["data"].get("output", {})
                if isinstance(output, dict) and not output.get("is_refusal", False):
                    yield _sse_event("token", {"content": no_rag_buffer})
                    no_rag_buffer = ""

        elif event_kind == "on_chain_end" and (
            event.get("name") == "LangGraph" or node == ""
        ):
            if current_sentence:
                yield _sse_event("token", {"content": current_sentence})
            output = event["data"].get("output", {})
            if isinstance(output, dict) and "ai_response" in output:
                final_state = output

    reference_contents = []
    for ref in (final_state.get("reference_contents") or []):
        if hasattr(ref, "document_id"):
            reference_contents.append({
                "document_id":   ref.document_id,
                "page":          ref.page,
                "content_index": ref.content_index,
                "text":          ref.text,
            })
        else:
            reference_contents.append(ref)

    yield _sse_event("done", {"reference_contents": reference_contents})

    yield _sse_event("_internal_state", {
        "rag_context":     final_state.get("rag_context"),
        "is_refusal":      final_state.get("is_refusal"),
        "word_to_explain": final_state.get("word_to_explain"),
        "node_costs":      final_state.get("node_costs", []),
    })
