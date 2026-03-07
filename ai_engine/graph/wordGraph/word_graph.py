"""LangGraph definition for the word explanation graph."""
from langgraph.graph import StateGraph, START, END

from .word_state import WordExplainState
from .word_nodes import (
    rag_retriever,
    word_explanation_agent,
    word_callback_router,
)

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
