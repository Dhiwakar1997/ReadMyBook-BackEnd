from typing import Annotated, Literal
from urllib.request import Request
from httpcore import request
from langgraph.graph import StateGraph, START, END
from langchain.chat_models import init_chat_model
from pydantic import BaseModel, Field
from typing_extensions import TypedDict
from langchain_core.messages import SystemMessage, HumanMessage
from ai_engine.prompts import RagRetrievalSystemPrompt, QueryRefinerSystemPrompt
from ai_engine.data.qdrantRepository import QdrantRepository
from ai_engine.service.textEmbeddingService import TextEmbeddingService
from documents.data.schema import AskDocumentRequest, ExplainWordDocumentRequest
from core.utils import get_context_block
from deepeval.test_case import LLMTestCase
from deepeval.metrics import FaithfulnessMetric, AnswerRelevancyMetric
from langchain_community.callbacks import get_openai_callback
import operator
import random
import time
import warnings

warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

llm = init_chat_model("openai:gpt-4.1", temperature= 0.7)
refiner_llm = init_chat_model("openai:gpt-4.1-mini", temperature=0)

EVAL_MODEL = "gpt-4.1-mini"
EVAL_THRESHOLD = 0.65

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

class QueryRefinerResponse(BaseModel):
    refined_query: str = Field(..., description="The rewritten, search-optimized version of the user's query.")
    user_query_language: str = Field(..., description="The detected language of the user's original query (e.g. 'English', 'Tamil', 'French').")
    chat_summary: str = Field("", description="A concise summary of the chat history capturing key topics discussed, questions asked, and answers given. Empty string if no prior history exists.")

class AgentResponse(BaseModel):
    ai_response: str = Field(
        ...,
        description="The AI's response to the user's message. This should be a detailed answer based on the provided context and guided by the instructions in the system prompt. Do not include (Document id - <document id> [SOURCE page <page number> | index <content index>]) in the response."
    )
    reference_contents: list[contextTracker] = Field(...,
        description="""Provide a list of up to five highly relevant context items used to generate the ai_response, actively prioritizing retrieval from different pages whenever possible. Each item must include the page number, content index, and the exact text from the context. The selected items should collectively cover the breadth of information used in the response, encouraging multi-page representation rather than multiple excerpts from a single page, unless unavoidable. Every item must have a confidence match score greater than 80% with the ai_response, be directly traceable to the claims made, and exclude any content that is marginal or unrelated."""
    )
    response_language:str=Field(...,description="Provide the language of the response provided by the ai agent")
    is_refusal: bool = Field(..., description="True if you could not answer the question from the provided context and responded with a refusal or 'I don't know' type answer. False if you provided a substantive informative answer.")

class State(TypedDict):
    ai_response: str | None
    reference_contents: list[contextTracker] | None
    current_context: str | None
    active_context: str | None
    rag_context: str | None
    retrieval_chunks: list[str] | None
    original_query: str | None
    original_query_language:str|None
    refined_query: str | None
    chat_summary: str | None
    evaluation: dict | None
    node_costs: Annotated[list, operator.add]
    total_cost: float | None
    document_id: str
    qdrant_repository: QdrantRepository
    text_embedding_service: TextEmbeddingService
    is_refusal: bool | None
    request_model: AskDocumentRequest
    request: Request

def query_refiner(state: State):
    t0 = time.perf_counter()
    chat_history = state["request_model"].chat_history or []

    if not chat_history:
        return {"original_query": "", "refined_query": ""}

    structured_refiner_llm = refiner_llm.with_structured_output(QueryRefinerResponse, method="json_schema")
    raw_query = chat_history[-1]["content"]
    # Skip refinement for first message (no history to resolve references from)
    if len(chat_history) <= 1:
        with get_openai_callback() as cb:
            result = structured_refiner_llm.invoke([
                SystemMessage(content=QueryRefinerSystemPrompt.format(language="English")),
                HumanMessage(content=f"User's query: {raw_query}"),
            ])
        latency = round((time.perf_counter() - t0) * 1000, 2)
        return {"original_query": raw_query, "refined_query": result.refined_query or raw_query,
                "chat_summary": "",
                "node_costs": [{"node": "query_refiner", "cost": cb.total_cost, "total_tokens": cb.total_tokens, "latency_ms": latency}]}

    history_text = "\n".join(
        f"{msg['role']}: {msg['content']}" for msg in chat_history[:-1][-6:]
    )

    with get_openai_callback() as cb:
        result = structured_refiner_llm.invoke([
            SystemMessage(content=QueryRefinerSystemPrompt.format(language="English")),
            HumanMessage(content=f"Chat history:\n{history_text}\n\nUser's latest query: {raw_query}"),
        ])

    latency = round((time.perf_counter() - t0) * 1000, 2)
    return {"original_query": raw_query, "original_query_language":result.user_query_language, "refined_query": result.refined_query or raw_query,
            "chat_summary": result.chat_summary or "",
            "node_costs": [{"node": "query_refiner", "cost": cb.total_cost, "total_tokens": cb.total_tokens, "latency_ms": latency}]}

def rag_retrieval_agent(state: State):
    t0 = time.perf_counter()
    print("RAG is fired.....")
    search_query = state.get("refined_query") or ""

    dense_query_vector = state["text_embedding_service"].embed_single_text(search_query)
    bm25_query_vector = state["text_embedding_service"].bm25_embed_texts([search_query])[0]

    matchQuery = {"value": state["document_id"]} if not state["request_model"].is_global_search else {"any": state["request"].state.accessible_documents}

    query_filter = {
            "must": [
                {
                    "key": "doc_id",
                    "match": matchQuery,
                }
            ]
        }

    vectorQueryResults = state["qdrant_repository"].search(dense_query_vector=dense_query_vector,
    bm25_query_vector=bm25_query_vector,query_filter=query_filter, top_k=5)

    context_block = get_context_block(vectorQueryResults)
    raw_chunks = vectorQueryResults.get("contexts", [])
    latency = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "rag_context": context_block,
        "retrieval_chunks": raw_chunks if raw_chunks else [context_block],
        "node_costs": [{"node": "rag_retrieval_agent", "cost": 0, "total_tokens": 0, "latency_ms": latency}],
    }


def chat_agent(state: State):
    t0 = time.perf_counter()
    classifier_llm = llm.with_structured_output(AgentResponse, method="json_schema")
    full_context = state.get("rag_context") if state.get("rag_context") else state.get("current_context","")
    active_context = state.get("active_context", "")
    original_query_language = state.get("original_query_language","English")
    chat_summary = state.get("chat_summary", "")

    messages = []
    # Use compact chat summary instead of full chat history to reduce latency
    if chat_summary:
        messages.append(SystemMessage(content=f"Conversation summary so far:\n{chat_summary}"))
    messages.append(SystemMessage(content=RagRetrievalSystemPrompt.format(full_context=full_context, active_context=active_context, response_language = original_query_language)))
    messages.append(HumanMessage(content=state.get("refined_query") or state.get("original_query", "")))

    with get_openai_callback() as cb:
        result = classifier_llm.invoke(messages)
    latency = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "ai_response": result.ai_response,
        "reference_contents": result.reference_contents,
        "is_refusal": result.is_refusal,
        "node_costs": [{"node": "chat_agent", "cost": cb.total_cost, "total_tokens": cb.total_tokens, "latency_ms": latency}]
    }

EVAL_SAMPLE_RATE = 0.10

def eval_node(state: State):
    t0 = time.perf_counter()
    user_input = state.get("original_query") or state.get("refined_query") or ""
    response = state.get("ai_response") or ""
    prev_costs = state.get("node_costs", [])

    # Build retrieval_context as a list of INDIVIDUAL chunks (not one blob)
    chunks = state.get("retrieval_chunks")
    if not chunks:
        fallback = state.get("current_context", "")
        chunks = [fallback] if fallback else []

    # Refusal detection — LLM self-classified via structured output
    if state.get("is_refusal"):
        total = sum(c["cost"] for c in prev_costs)
        latency = round((time.perf_counter() - t0) * 1000, 2)
        return {
            "evaluation": {"faithfulness": 0.0, "response_relevancy": 0.0, "refusal_detected": True, "metrics_sampled": False},
            "node_costs": [{"node": "eval_node", "cost": 0, "total_tokens": 0, "latency_ms": latency}],
            "total_cost": total
        }

    # Decide whether to run expensive DeepEval metrics (10% sampling)
    run_metrics = random.random() < EVAL_SAMPLE_RATE and user_input and response

    if not run_metrics:
        total = sum(c["cost"] for c in prev_costs)
        latency = round((time.perf_counter() - t0) * 1000, 2)
        return {
            "evaluation": {"faithfulness": None, "response_relevancy": None, "metrics_sampled": False},
            "node_costs": [{"node": "eval_node", "cost": 0, "total_tokens": 0, "latency_ms": latency}],
            "total_cost": total
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
        return {"evaluation": {"faithfulness": None, "response_relevancy": None, "error": str(e), "metrics_sampled": True},
                "node_costs": [{"node": "eval_node", "cost": 0, "total_tokens": 0, "latency_ms": latency}], "total_cost": total}

    total = sum(c["cost"] for c in prev_costs) + eval_cost
    latency = round((time.perf_counter() - t0) * 1000, 2)

    evaluation = {
        "faithfulness": round(float(faithfulness_score), 4) if faithfulness_score is not None else None,
        "response_relevancy": round(float(relevancy_score), 4) if relevancy_score is not None else None,
        "metrics_sampled": True,
    }
    return {"evaluation": evaluation,
            "node_costs": [{"node": "eval_node", "cost": eval_cost, "total_tokens": eval_tokens, "latency_ms": latency}],
            "total_cost": total}

def chat_callback_router(state: State) -> Literal["eval_node", "rag_retrieval_agent"]:
    if state.get("is_refusal", True):
        return "rag_retrieval_agent"
    return "eval_node"

graph_builder = StateGraph(State)

graph_builder.add_node("query_refiner", query_refiner)
graph_builder.add_node("rag_retrieval_agent", rag_retrieval_agent)
graph_builder.add_node("chat_agent", chat_agent)
graph_builder.add_node("eval_node", eval_node)

graph_builder.add_edge(START, "query_refiner")
graph_builder.add_edge("query_refiner", "chat_agent")
graph_builder.add_edge("rag_retrieval_agent", "chat_agent")
graph_builder.add_conditional_edges("chat_agent", chat_callback_router, {
    "eval_node": "eval_node",
    "rag_retrieval_agent": "rag_retrieval_agent",
})
graph_builder.add_edge("eval_node", END)
chatGraph = graph_builder.compile()

def get_ai_chat_response(document_id:str, request: Request, request_model: AskDocumentRequest) -> dict:

    current_context =  f"Document id: {document_id} - {request_model.current_context}"

    state: State = {
        "current_context": current_context,
        "active_context": request_model.active_context,
        "rag_context": None,
        "retrieval_chunks": None,
        "original_query": None,
        "original_query_language":None,
        "refined_query": None,
        "chat_summary": None,
        "ai_response": None,
        "reference_contents": None,
        "is_refusal": None,
        "evaluation": None,
        "node_costs": [],
        "total_cost": None,
        "qdrant_repository":QdrantRepository() ,
        "text_embedding_service": TextEmbeddingService(),
        "request_model":request_model,
        "request": request,
        "document_id": document_id
    }
    result = chatGraph.invoke(state)
    return result


