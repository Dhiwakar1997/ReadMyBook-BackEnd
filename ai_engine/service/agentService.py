from ai_engine.graph.askGraph import get_ai_chat_response, stream_ai_chat_response
from ai_engine.graph.explainWordGraph import get_ai_word_explanation, stream_ai_word_explanation
from documents.data.schema import AskDocumentRequest, ExplainWordDocumentRequest
from typing import AsyncGenerator

from fastapi import HTTPException, Request
import json

class AgentService:
    def __init__(self, ):
        pass

    async def ask_the_rag(self, askDocumentRequest: AskDocumentRequest, document_id:str,request:Request, top_k: int = 5):
        try:
            result = await get_ai_chat_response(document_id=document_id, request=request, request_model=askDocumentRequest)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"LLM request failed: {exc}")

        return result

    async def ask_the_rag_stream(
        self,
        askDocumentRequest: AskDocumentRequest,
        document_id: str,
        request: Request,
    ) -> AsyncGenerator[str, None]:
        """Async generator that streams SSE events for the ask endpoint."""
        try:
            async for event in stream_ai_chat_response(
                document_id=document_id,
                request=request,
                request_model=askDocumentRequest,
            ):
                yield event
        except Exception as exc:
            import traceback
            traceback.print_exc()
            yield f"event: error\ndata: {json.dumps({'detail': str(exc)})}\n\n"

    async def getWordExplanation(self, request_model: ExplainWordDocumentRequest, document_id: str, request: Request) -> dict:
        try:
            result = await get_ai_word_explanation(document_id=document_id, request=request, request_model=request_model)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"LLM request failed: {exc}")

        return result

    async def getWordExplanationStream(
        self,
        request_model: ExplainWordDocumentRequest,
        document_id: str,
        request: Request,
    ) -> AsyncGenerator[str, None]:
        """Async generator that streams SSE events for the explain-word endpoint."""
        try:
            async for event in stream_ai_word_explanation(
                document_id=document_id,
                request=request,
                request_model=request_model,
            ):
                yield event
        except Exception as exc:
            import traceback
            traceback.print_exc()
            yield f"event: error\ndata: {json.dumps({'detail': str(exc)})}\n\n"