from typing import Annotated, Literal
from urllib.request import Request
from httpcore import request
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain.chat_models import init_chat_model
from pydantic import BaseModel, Field
from typing_extensions import TypedDict
from langchain_core.messages import SystemMessage, HumanMessage
from ai_engine.prompts import RagRetrievalSystemPrompt, QueryRefinerSystemPrompt
from ai_engine.data.qdrantRepository import QdrantRepository
from ai_engine.service.textEmbeddingService import TextEmbeddingService
from documents.data.schema import AskDocumentRequest, ExplainWordDocumentRequest
from core.utils import get_context_block
from ragas import SingleTurnSample
from ragas.metrics import Faithfulness, ResponseRelevancy
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from langchain_openai import OpenAIEmbeddings
from langchain_community.callbacks import get_openai_callback
import operator
import asyncio
import warnings

warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

llm = init_chat_model("openai:gpt-4.1", temperature= 0.7)
refiner_llm = init_chat_model("openai:gpt-4.1-mini", temperature=0)

eval_llm = LangchainLLMWrapper(init_chat_model("openai:gpt-4.1-mini", temperature=0))
eval_embeddings = LangchainEmbeddingsWrapper(OpenAIEmbeddings(model="text-embedding-3-small"))
faithfulness_metric = Faithfulness(llm=eval_llm)
relevancy_metric = ResponseRelevancy(llm=eval_llm, embeddings=eval_embeddings)

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

class AgentResponse(BaseModel):
    ai_response: str = Field(
        ...,
        description="The AI's response to the user's message. This should be a detailed answer based on the provided context and guided by the instructions in the system prompt. Do not include (Document id - <document id> [SOURCE page <page number> | index <content index>]) in the response."
    )
    reference_contents: list[contextTracker] = Field(...,
        description="""Provide a list of up to five highly relevant context items used to generate the ai_response, actively prioritizing retrieval from different pages whenever possible. Each item must include the page number, content index, and the exact text from the context. The selected items should collectively cover the breadth of information used in the response, encouraging multi-page representation rather than multiple excerpts from a single page, unless unavoidable. Every item must have a confidence match score greater than 80% with the ai_response, be directly traceable to the claims made, and exclude any content that is marginal or unrelated."""
    )
    response_language:str=Field(...,description="Provide the language of the response provided by the ai agent")

class State(TypedDict):
    # Messages have the type "list". The `add_messages` function
    # in the annotation defines how this state key should be updated
    # (in this case, it appends messages to the list, rather than overwriting them)
    past_chat_history: list[dict]
    messages: Annotated[list, add_messages]
    ai_response: str | None
    reference_contents: list[contextTracker] | None
    current_context: str | None
    active_context: str | None
    rag_context: str | None
    original_query: str | None
    original_query_language:str|None
    refined_query: str | None
    evaluation: dict | None
    node_costs: Annotated[list, operator.add]
    total_cost: float | None
    document_id: str
    qdrant_repository: QdrantRepository
    text_embedding_service: TextEmbeddingService
    request_model: AskDocumentRequest
    request: Request

def query_refiner(state: State):
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
        return {"original_query": raw_query, "refined_query": result.refined_query or raw_query,
                "node_costs": [{"node": "query_refiner", "cost": cb.total_cost, "total_tokens": cb.total_tokens}]}

    history_text = "\n".join(
        f"{msg['role']}: {msg['content']}" for msg in chat_history[:-1][-6:]
    )

    with get_openai_callback() as cb:
        result = structured_refiner_llm.invoke([
            SystemMessage(content=QueryRefinerSystemPrompt.format(language="English")),
            HumanMessage(content=f"Chat history:\n{history_text}\n\nUser's latest query: {raw_query}"),
        ])
    return {"original_query": raw_query, "original_query_language":result.user_query_language, "refined_query": result.refined_query or raw_query,
            "node_costs": [{"node": "query_refiner", "cost": cb.total_cost, "total_tokens": cb.total_tokens}]}

def rag_retrieval_agent(state: State):
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
    bm25_query_vector=bm25_query_vector,query_filter=query_filter, top_k=20)

    context_block = get_context_block(vectorQueryResults)
    return {
        "rag_context": context_block
    }

def loadPastChatHistory(state:State):
    past_chat_history = state.get("past_chat_history", [])
    for chat in past_chat_history:
        role = chat.get("role", "user")
        content = chat.get("content", "")
        if role in ["user","human"]:
            state["messages"].append(
                HumanMessage(content=content)
            )
        elif role in ["assistant","ai","bot","system"]:
            state["messages"].append(
                SystemMessage(content=content)
            )
    return state

def chat_agent(state: State):
    classifier_llm = llm.with_structured_output(AgentResponse, method="json_schema")
    full_context = state.get("rag_context") if state.get("rag_context") else state.get("current_context","")
    active_context = state.get("active_context", "")
    original_query_language = state.get("original_query_language","English")

    messages = [
        *state["messages"][:-1],
        SystemMessage(content=RagRetrievalSystemPrompt.format(full_context=full_context, active_context=active_context, response_language = original_query_language)),
        state["messages"][-1]
    ]
    with get_openai_callback() as cb:
        result = classifier_llm.invoke(messages)
    return {
        "ai_response": result.ai_response,
        "reference_contents": result.reference_contents,
        "node_costs": [{"node": "chat_agent", "cost": cb.total_cost, "total_tokens": cb.total_tokens}]
    }

def eval_node(state: State):
    user_input = state.get("original_query") or state.get("refined_query") or ""
    response = state.get("ai_response") or ""
    contexts = [state.get("rag_context") if state.get("rag_context") else state.get("current_context","")]
    
    if not user_input or not response:
        prev_costs = state.get("node_costs", [])
        total = sum(c["cost"] for c in prev_costs)
        return {"evaluation": {"faithfulness": None, "response_relevancy": None}, "total_cost": total}

    sample = SingleTurnSample(
        user_input=user_input,
        response=response,
        retrieved_contexts=contexts,
    )

    try:
        with get_openai_callback() as cb:
            loop = asyncio.new_event_loop()
            faithfulness_score = loop.run_until_complete(
                faithfulness_metric.single_turn_ascore(sample)
            )
            relevancy_score = loop.run_until_complete(
                relevancy_metric.single_turn_ascore(sample)
            )
            loop.close()
    except Exception as e:
        print(f"[eval_node] ERROR: {e}")
        prev_costs = state.get("node_costs", [])
        total = sum(c["cost"] for c in prev_costs)
        return {"evaluation": {"faithfulness": None, "response_relevancy": None, "error": str(e)},
                "node_costs": [{"node": "eval_node", "cost": 0, "total_tokens": 0}], "total_cost": total}

    eval_cost = cb.total_cost
    prev_costs = state.get("node_costs", [])
    total = sum(c["cost"] for c in prev_costs) + eval_cost

    evaluation = {
        "faithfulness": round(float(faithfulness_score), 4),
        "response_relevancy": round(float(relevancy_score), 4),
    }
    print(f"[eval_node] {evaluation} | total_cost: ${total:.6f}")
    return {"evaluation": evaluation,
            "node_costs": [{"node": "eval_node", "cost": eval_cost, "total_tokens": cb.total_tokens}],
            "total_cost": total}

def eval_callback_router(state: State) -> Literal["end", "rag_retrieval_agent"]:
    if state.get("rag_context") is not None:
        return "end"
    evaluation = state.get("evaluation") or {}
    faithful = evaluation.get("faithfulness")
    if faithful is None or faithful >= 0.65:
        return "end"
    return "rag_retrieval_agent"

graph_builder = StateGraph(State)

graph_builder.add_node("loadPastChatHistory",loadPastChatHistory)
graph_builder.add_node("query_refiner", query_refiner)
graph_builder.add_node("rag_retrieval_agent", rag_retrieval_agent)
graph_builder.add_node("chat_agent",chat_agent)
graph_builder.add_node("eval_node", eval_node)

graph_builder.add_edge(START, "loadPastChatHistory")
graph_builder.add_edge("loadPastChatHistory", "query_refiner")
graph_builder.add_edge("query_refiner", "chat_agent")
graph_builder.add_edge("chat_agent", "eval_node")
graph_builder.add_conditional_edges("eval_node", eval_callback_router, {
    "end": END,
    "rag_retrieval_agent": "rag_retrieval_agent",
})
graph_builder.add_edge("rag_retrieval_agent", "chat_agent")
chatGraph = graph_builder.compile()

def get_ai_chat_response(document_id:str, request: Request, request_model: AskDocumentRequest) -> dict:

    current_context =  f"Document id: {document_id} - {request_model.current_context}"

    state: State = {
        "past_chat_history": request_model.chat_history or [],
        "current_context": current_context,
        "active_context": request_model.active_context,
        "rag_context": None,
        "original_query": None,
        "original_query_language":None,
        "refined_query": None,
        "messages": [],
        "ai_response": None,
        "reference_contents": None,
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


