from typing import Annotated, Literal
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain.chat_models import init_chat_model
from pydantic import BaseModel, Field
from typing_extensions import TypedDict
from langchain_core.messages import SystemMessage, HumanMessage
from ai_engine.prompts import RagRetrievalSystemPrompt

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

class RagResponse(BaseModel):
    ai_response: str = Field(
        ...,
        description="The AI's response to the user's message. This should be a detailed answer based on the provided context and guided by the instructions in the system prompt. Do not include (Document id - <document id> [SOURCE page <page number> | index <content index>]) in the response."
    )
    reference_contents: list[contextTracker] = Field(...,
        description="""Provide a list of up to five highly relevant context items used to generate the ai_response, actively prioritizing retrieval from different pages whenever possible. Each item must include the page number, content index, and the exact text from the context. The selected items should collectively cover the breadth of information used in the response, encouraging multi-page representation rather than multiple excerpts from a single page, unless unavoidable. Every item must have a confidence match score greater than 80% with the ai_response, be directly traceable to the claims made, and exclude any content that is marginal or unrelated."""
    )



class State(TypedDict):
    # Messages have the type "list". The `add_messages` function
    # in the annotation defines how this state key should be updated
    # (in this case, it appends messages to the list, rather than overwriting them)
    past_chat_history: list[dict]
    messages: Annotated[list, add_messages]
    context_str: str | None
    ai_response: str | None
    reference_contents: list[contextTracker] | None
    current_context: str | None

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

def rag_agent(state: State):
    classifier_llm = llm.with_structured_output(RagResponse)
    full_context = state.get("context_str", "")
    current_context = state.get("current_context", "")
    messages = [
        *state["messages"][:-1],
        SystemMessage(content=RagRetrievalSystemPrompt.format(full_context=full_context, current_context=current_context)),
        state["messages"][-1]
    ]
    result = classifier_llm.invoke(messages)
    return {
        "ai_response": result.ai_response,
        "reference_contents": result.reference_contents
    }

graph_builder = StateGraph(State)

graph_builder.add_node("loadPastChatHistory",loadPastChatHistory)
graph_builder.add_node("rag_agent",rag_agent)

graph_builder.add_edge(START, "loadPastChatHistory")
graph_builder.add_edge("loadPastChatHistory", "rag_agent")
graph_builder.add_edge("rag_agent", END)

chatGraph = graph_builder.compile()

def get_ai_chat_response(chat_history: list[dict],current_context: str , context_str: str) -> dict:
    state: State = {
        "past_chat_history": chat_history,
        "current_context": current_context,
        "messages": [],
        "context_str": context_str,
        "ai_response": None,
        "reference_contents": None
    }
    result = chatGraph.invoke(state)
    return result


