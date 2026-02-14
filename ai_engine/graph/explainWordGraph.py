from ai_engine.data.qdrantRepository import QdrantRepository
from ai_engine.service.textEmbeddingService import TextEmbeddingService
from documents.data.schema import ExplainWordDocumentRequest
from core.utils import get_context_block
from langgraph.graph import StateGraph, START, END
from langchain.chat_models import init_chat_model
from pydantic import BaseModel, Field
from typing_extensions import TypedDict
from langchain_core.messages import SystemMessage, HumanMessage
from websockets import State
from ai_engine.prompts import WordExplainSystemPrompt
from fastapi import Request

llm = init_chat_model("openai:gpt-4.1", temperature= 0.7)


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
    ai_response: str = Field(
        ...,
        description="The AI's response to the user's message. This should be a detailed answer based on the provided context and guided by the instructions in the system prompt. Do not include (Document id - <document id> [SOURCE page <page number> | index <content index>]) in the response."
    )
    reference_contents: list[contextTracker] = Field(...,
        description="""Provide a list of up to five highly relevant context items used to generate the ai_response, actively prioritizing retrieval from different pages whenever possible. Each item must include the page number, content index, and the exact text from the context. The selected items should collectively cover the breadth of information used in the response, encouraging multi-page representation rather than multiple excerpts from a single page, unless unavoidable. Every item must have a confidence match score greater than 80% with the ai_response, be directly traceable to the claims made, and exclude any content that is marginal or unrelated."""
    )



class WordExplainState(TypedDict):
    # Messages have the type "list". The `add_messages` function
    # in the annotation defines how this state key should be updated
    # (in this case, it appends messages to the list, rather than overwriting them)
    document_id: str
    rag_context: str | None
    current_context: str | None
    active_context: str | None
    word_to_explain: str | None
    ai_response: str | None
    reference_contents: list[contextTracker] | None
    qdrant_repository: QdrantRepository
    text_embedding_service: TextEmbeddingService
    request_model: ExplainWordDocumentRequest
    request: Request


def rag_retriever(state: WordExplainState):
    dense_query_vector = state["text_embedding_service"].embed_single_text(state["request_model"].word_to_explain)
    bm25_query_vector = state["text_embedding_service"].bm25_embed_texts([state["request_model"].word_to_explain])[0]

    matchQuery = {"value": state["document_id"]} if not state["request_model"].is_global_search else {"any": state["request"].state.accessible_documents}
            
    query_filter = {
            "must": [
                {
                    "key": "doc_id",
                    "match": matchQuery,
                }
            ]
        }
    vectorQueryResults = state["qdrant_repository"].search(dense_query_vector=dense_query_vector, bm25_query_vector=bm25_query_vector,query_filter=query_filter, top_k=20, alpha=0.3)

    context_block = get_context_block(vectorQueryResults)

    return {
        "rag_context":context_block
    }
    

def word_explanation_agent(state: WordExplainState):
    classifier_llm = llm.with_structured_output(AgentResponse)
    current_context = state.get("current_context", "")
    active_context = state.get("active_context", "")
    word_to_explain = state.get("word_to_explain", "")
    messages = [

        SystemMessage(content=WordExplainSystemPrompt.format(
            full_context=current_context,
            active_context=active_context,
            word_to_explain=word_to_explain)),

    ]
    result = classifier_llm.invoke(messages)
    return {
        "ai_response": result.ai_response,
        "reference_contents": result.reference_contents
    }

graph_builder = StateGraph(WordExplainState)

graph_builder.add_node("rag_retriever", rag_retriever)
graph_builder.add_node("word_explanation_agent",word_explanation_agent)

graph_builder.add_edge(START, "rag_retriever")
graph_builder.add_edge("rag_retriever", "word_explanation_agent")
graph_builder.add_edge("word_explanation_agent", END)

chatGraph = graph_builder.compile()

def get_ai_word_explanation(document_id: str, request: Request,request_model: ExplainWordDocumentRequest) -> dict:

    current_context =  f"Document id: {document_id} - {request_model.current_context}"
    qdrant_repository = QdrantRepository()
    text_embedding_service = TextEmbeddingService()
    state: WordExplainState = {
        "document_id": document_id,
        "current_context": current_context ,
        "active_context": request_model.active_context,
        "rag_context": None,
        "word_to_explain": request_model.word_to_explain,
        "ai_response": None,
        "reference_contents": None,
        "qdrant_repository":qdrant_repository,
        "text_embedding_service": text_embedding_service,
        "request_model":request_model,
        "request": request
    }
    result = chatGraph.invoke(state)
    return result