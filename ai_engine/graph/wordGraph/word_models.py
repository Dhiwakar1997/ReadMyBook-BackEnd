"""Pydantic models for the word explanation graph."""
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


class AgentResponse(BaseModel):
    reference_contents: list[ContextTracker] = Field(
        ...,
        description="Provide a list of up to five highly relevant context items used to generate the response.",
    )
    is_refusal: bool = Field(
        ...,
        description="True if you could not answer the question from the provided context and responded with a refusal or 'I don't know' type answer. False if you provided a substantive informative answer.",
    )
