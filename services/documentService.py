from data.models.documentsModel import Document
from data.repositories.documentRepository import DocumentRepository
from data.schemas.documentSchema import CreateDocumentRequest, UpdateDocumentRequest
from sqlalchemy.orm import Session
from fastapi import Depends, Request, HTTPException
from data.dbClient import get_db
from data.repositories.qdrantVecorRepository import QdrantStorage
from services.azureBlobService import AzureBlobService
from services.textEmbeddingService import TextEmbeddingService
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

import os
import ulid
import datetime

class DocumentService:
    def __init__(self, db: Session, request: Request):
        self.document_repository = DocumentRepository(db)
        self.request = request

    def get_all_documents(self):
        all_documents_dict = {}
        all_documents = self.document_repository.get_all_documents(self.request.state.user_id)
        for document in all_documents:
            all_documents_dict[document.document_id] = document
        return all_documents_dict

    def get_document_by_id(self, document_id: str):
        document = self.document_repository.get_document_by_id(document_id=document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        return document

    def create_document(self, document: CreateDocumentRequest):
        document = Document(
            document_id="doc_"+str(ulid.new()),
            display_name=document.display_name,
            size_in_kilobyes=document.size_in_kilobyes,
            owner_id=self.request.state.user_id,
            created_at=datetime.datetime.now(),
            updated_at=datetime.datetime.now(),
            deleted_at=None,
            is_deleted=False,
            is_active=False,
            images=[],
            markdown_parse_time=None,
        )
        created_document = self.document_repository.create_document(document)

        return created_document
    
    def update_document(self, document_id: str, update_document: UpdateDocumentRequest):
        document = self.document_repository.get_document_by_id(document_id=document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        if update_document.display_name:
            document.display_name = update_document.display_name
        if update_document.is_active is not None:
            document.is_active = update_document.is_active
        document.updated_at = datetime.datetime.now()
        updated_document = self.document_repository.update_document(document)
        return updated_document

    def delete_document(self, document_id: str):
        document = self.document_repository.get_document_by_id(document_id=document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        is_deleted = self.document_repository.delete_document(document)
        return is_deleted
    
    def ask_document(self, request: Request, document_id: str, question: str):
        qdrantRepo = QdrantStorage()
        embedding_service = TextEmbeddingService()
        query_vector = embedding_service.embed_single_text(question)
        query_filter = {
            "must": [
                {
                    "key": "doc_id",
                    "match": {
                        "any": request.state.accessible_documents,
                    }
                }
            ]
        }

        found = qdrantRepo.search(query_vector=query_vector, query_filter=query_filter, top_k=5)
        context_block = "\n\n".join(f"- {c}" for c in found.get("contexts", []))
        user_content = (
            "Use the following context to answer the question.\n\n"
            f"Context:\n{context_block}\n\n"
            f"Question: {question}\n"
            "Answer concisely using the context above."
        )

        if not os.getenv("OPENAI_API_KEY"):
            raise HTTPException(
                status_code=500,
                detail="OPENAI_API_KEY is not set on the server",
            )

        model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        llm = ChatOpenAI(model=model_name, temperature=0.2)
        try:
            result = llm.invoke([HumanMessage(content=user_content)])
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"LLM request failed: {exc}")

        answer = getattr(result, "content", None) or ""
        return {"answer": answer.strip()}

    def explain_text(self, request: Request, text: str):
        qdrantRepo = QdrantStorage()
        embedding_service = TextEmbeddingService()
        query_vector = embedding_service.embed_single_text(text)
        query_filter = {
            "must": [
                {
                    "key": "doc_id",
                    "match": {
                        "any": request.state.accessible_documents,
                    }
                }
            ]
        }
        found = qdrantRepo.search(query_vector=query_vector, query_filter=query_filter, top_k=5)
        context_block = "\n\n".join(f"- {c}" for c in found.get("contexts", []))
        model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        llm = ChatOpenAI(model=model_name, temperature=0.2)
        user_content = (
            "Explain the following text in simple terms with the context provided:\n\n"
            f"Context:\n{context_block}\n\n"
            f"Text:\n{text}\n\n"
            "Explanation:"
        )
        try:
            result = llm.invoke([HumanMessage(content=user_content)])
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"LLM request failed: {exc}")

        explanation = getattr(result, "content", None) or ""
        return {"explanation": explanation.strip()}