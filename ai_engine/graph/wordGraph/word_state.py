"""State TypedDict and initial state factory for the word explanation graph."""
import operator
from typing import Annotated

from typing_extensions import TypedDict
from fastapi import Request

from ai_engine.data.qdrantRepository import QdrantRepository
from ai_engine.service.textEmbeddingService import TextEmbeddingService
from documents.data.schema import ExplainWordDocumentRequest

from .word_models import ContextTracker


class WordExplainState(TypedDict, total=False):
    original_document_id: str
    rag_context: str | None
    current_context: str | None
    active_context: str | None
    word_to_explain: str | None
    ai_response: str | None
    reference_contents: list[ContextTracker] | None
    is_refusal: bool | None
    node_costs: Annotated[list, operator.add]
    qdrant_repository: QdrantRepository
    text_embedding_service: TextEmbeddingService
    request_model: ExplainWordDocumentRequest
    request: Request


def create_word_explain_state(
    document_id: str,
    request: Request,
    request_model: ExplainWordDocumentRequest,
) -> dict:
    """Build initial state for the word explanation graph."""
    current_context = f"Document id: {document_id} - {request_model.current_context}"
    return {
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
