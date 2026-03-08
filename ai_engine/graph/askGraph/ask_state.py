"""State TypedDict and initial state factory for the ask (RAG chat) graph."""
import operator
from typing import Annotated

from typing_extensions import TypedDict
from fastapi import Request

from ai_engine.data.qdrantRepository import QdrantRepository
from ai_engine.service.textEmbeddingService import TextEmbeddingService
from documents.data.schema import AskDocumentRequest

from .ask_models import ContextTracker


class State(TypedDict, total=False):
    ai_response: str | None
    reference_contents: list[ContextTracker] | None
    current_context: str | None
    active_context: str | None
    rag_context: str | None
    retrieval_chunks: list[str] | None
    original_query: str | None
    original_query_language: str | None
    refined_query: str | None
    chat_summary: str | None
    evaluation: dict | None
    node_costs: Annotated[list, operator.add]
    total_cost: float | None
    original_document_id: str
    qdrant_repository: QdrantRepository
    text_embedding_service: TextEmbeddingService
    is_refusal: bool | None
    is_followup: bool | None
    rag_top_k: int | None
    category: str | None
    sub_categories: list[str] | None
    request_model: AskDocumentRequest
    request: Request


def create_ask_state(
    document_id: str,
    request: Request,
    request_model: AskDocumentRequest,
    category: str | None = None,
    sub_categories: list[str] | None = None,
) -> dict:
    """Build initial state for the ask graph. Returns a dict suitable for State."""
    current_context = f"Document id: {document_id} - {request_model.current_context}"
    return {
        "current_context": current_context,
        "active_context": request_model.active_context,
        "rag_context": None,
        "retrieval_chunks": None,
        "original_query": None,
        "original_query_language": None,
        "refined_query": None,
        "chat_summary": None,
        "ai_response": None,
        "reference_contents": None,
        "is_refusal": None,
        "is_followup": False,
        "rag_top_k": 5,
        "category": category,
        "sub_categories": sub_categories,
        "evaluation": None,
        "node_costs": [],
        "total_cost": None,
        "qdrant_repository": QdrantRepository(),
        "text_embedding_service": TextEmbeddingService(),
        "request_model": request_model,
        "request": request,
        "original_document_id": document_id,
    }
