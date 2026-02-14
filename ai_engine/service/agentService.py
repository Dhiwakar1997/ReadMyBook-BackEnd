from ai_engine.graph.askGraph import get_ai_chat_response
from ai_engine.graph.explainWordGraph import get_ai_word_explanation
from documents.data.schema import AskDocumentRequest, ExplainWordDocumentRequest

from fastapi import HTTPException, Request

class AgentService:
    def __init__(self, ):
        pass

    def ask_the_rag(self, askDocumentRequest: AskDocumentRequest, document_id:str,request:Request, top_k: int = 5):
        try:
            result = get_ai_chat_response(document_id=document_id, request=request, request_model=askDocumentRequest)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"LLM request failed: {exc}")

        return result
    
    
    def getWordExplanation(self,request_model: ExplainWordDocumentRequest, document_id:str, request:Request) -> dict:
        try:
            result = get_ai_word_explanation(document_id=document_id, request=request, request_model=request_model)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"LLM request failed: {exc}")

        return result   