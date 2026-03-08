"""LangGraph definition for the ask (RAG chat) graph."""
from langgraph.graph import StateGraph, START, END

from .ask_state import State
from .ask_nodes import (
    query_refiner,
    query_refiner_router,
    rag_retrieval_agent,
    chat_agent,
    chat_callback_router,
)

graph_builder = StateGraph(State)
graph_builder.add_node("query_refiner", query_refiner)
graph_builder.add_node("rag_retrieval_agent", rag_retrieval_agent)
graph_builder.add_node("chat_agent", chat_agent)
graph_builder.add_edge(START, "query_refiner")
graph_builder.add_conditional_edges("query_refiner", query_refiner_router, {
    "__end__": END,
    "chat_agent": "chat_agent",
    "rag_retrieval_agent": "rag_retrieval_agent",
})
graph_builder.add_edge("rag_retrieval_agent", "chat_agent")
graph_builder.add_conditional_edges("chat_agent", chat_callback_router, {
    "__end__": END,
    "rag_retrieval_agent": "rag_retrieval_agent",
})
chatGraph = graph_builder.compile()
