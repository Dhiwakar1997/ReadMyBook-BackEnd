from ai_engine.data.qdrantRepository import QdrantRepository
from ai_engine.service.textEmbeddingService import TextEmbeddingService
from ai_engine.graph.askGraph import get_ai_chat_response
from ai_engine.graph.explainWordGraph import get_ai_word_explanation
from documents.data.schema import AskDocumentRequest, ExplainWordDocumentRequest


from fastapi import HTTPException, Request

class RagService:
    def __init__(self, ):
        self.qdrant_repository = QdrantRepository()
        self.text_embedding_service = TextEmbeddingService()

    def ask_the_rag(self, askDocumentRequest: AskDocumentRequest, document_id:str,request:Request, top_k: int = 5):

        chat_history = askDocumentRequest.chat_history or []
        currentContext = askDocumentRequest.current_context or ""
        isGlobalSearch = askDocumentRequest.is_global_search
        userQuestion = ""
        if chat_history:
            userQuestion = chat_history[-1]["content"]

        query_vector = self.text_embedding_service.embed_single_text(userQuestion)

        matchQuery = {"value": document_id} if not isGlobalSearch else {"any": request.state.accessible_documents}
            
        query_filter = {
            "must": [
                {
                    "key": "doc_id",
                    "match": matchQuery,
                }
            ]
        }

        vectorQueryResults = self.qdrant_repository.search(query_vector=query_vector, query_filter=query_filter, top_k=top_k)

        context_block = self.get_context_block(vectorQueryResults)
        try:
            result = get_ai_chat_response(chat_history=chat_history,current_context=currentContext,context_str=context_block)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"LLM request failed: {exc}")

        return result
    
    def get_context_block(self, data:dict) -> str:
        contexts = data.get("contexts", [])
        sources = data.get("sources", [])
        context_block = "\n\n".join(f"([Document id: {s}]) - {c}" for c, s in zip(contexts, sources))
        return context_block
    
    def getWordExplanation(self,request_model: ExplainWordDocumentRequest, document_id:str, request:Request, top_k:int=3) -> dict:
        query_vector = self.text_embedding_service.embed_single_text(request_model.word_to_explain)

        matchQuery = {"value": document_id} if not request_model.is_global_search else {"any": request.state.accessible_documents}
            
        query_filter = {
            "must": [
                {
                    "key": "doc_id",
                    "match": matchQuery,
                }
            ]
        }

        vectorQueryResults = self.qdrant_repository.search(query_vector=query_vector, query_filter=query_filter, top_k=top_k)

        context_block = self.get_context_block(vectorQueryResults)
        current_context = request_model.current_context
        try:
            result = get_ai_word_explanation(current_context=current_context, full_context_str=context_block, word_to_explain=request_model.word_to_explain)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"LLM request failed: {exc}")

        return result   