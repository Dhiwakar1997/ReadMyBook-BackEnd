"""Pydantic models for the ask (RAG chat) graph."""
from pydantic import BaseModel, Field


class ContextTracker(BaseModel):
    document_id: str = Field(
        ...,
        description="The unique identifier of the document from which the context was taken.",
    )
    page: int = Field(
        ...,
        description="The source page number from which the context was taken.",
    )
    content_index: int = Field(
        ...,
        description="The source index of the content block from which the context was taken.",
    )
    text: str = Field(
        ...,
        description="The source actual text content used as context.",
    )


class QueryRefinerResponse(BaseModel):
    refined_query: str = Field(
        ...,
        description="The rewritten, search-optimized version of the user's query.",
    )
    user_query_language: str = Field(
        ...,
        description="The detected language of the user's original query (e.g. 'English', 'Tamil', 'French').",
    )
    chat_summary: str = Field(
        "",
        description="A concise summary of the chat history capturing key topics discussed, questions asked, and answers given. Empty string if no prior history exists.",
    )


class AgentResponse(BaseModel):
    reference_contents: list[ContextTracker] = Field(
        ...,
        description="""Provide a list of up to five highly relevant context items used to generate the ai_response, actively prioritizing retrieval from different pages whenever possible. Each item must include the page number, content index, and the exact text from the context. The selected items should collectively cover the breadth of information used in the response, encouraging multi-page representation rather than multiple excerpts from a single page, unless unavoidable. Every item must have a confidence match score greater than 80% with the ai_response, be directly traceable to the claims made, and exclude any content that is marginal or unrelated.""",
    )
    response_language: str = Field(
        ...,
        description="Provide the language of the response provided by the ai agent",
    )
    is_refusal: bool = Field(
        ...,
        description="True if you could not answer the question from the provided context and responded with a refusal or 'I don't know' type answer. False if you provided a substantive informative answer.",
    )


# Backward compatibility alias (legacy name used in State and callers)
contextTracker = ContextTracker
