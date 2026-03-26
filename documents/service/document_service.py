from documents.data.model import Document
from documents.data.repository import DocumentRepository, DocumentAccessRepository, DocumentAccessRequestRepository, CachedDocumentRepository
from documents.data.original_document.repository import OriginalDocumentRepository
from documents.data.schema import CreateDocumentRequest, UpdateDocumentRequest, AskDocumentRequest, ExplainWordDocumentRequest
from sqlalchemy.orm import Session
from fastapi import Request, HTTPException
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator
from ai_engine.service.agentService import AgentService
from users.data.repository import UserRepository
from shared.redis import RedisService
from core.db_client import SessionLocal
from worker.vectorHelper import delete_vectors_by_doc_id
from events import producer as kafka

import ulid
import json
import datetime
import time
import logging

logger = logging.getLogger(__name__)


class DocumentService:
    def __init__(self, db: Session, request: Request):
        self.db = db
        self.document_repository = CachedDocumentRepository(DocumentRepository(db), RedisService())
        self.document_access_repository = DocumentAccessRepository(db)
        self.document_access_request_repository = DocumentAccessRequestRepository(db)
        self.original_document_repository = OriginalDocumentRepository(db)
        self.request = request
        self.redis_service = RedisService()

    def get_all_documents(self, include_images: bool = False):
        doc_ids = self.accesible_doc_ids()
        if not doc_ids:
            return {}
        documents = self.document_repository.get_all_documents(doc_ids, include_images=include_images)
        return {doc.document_id: doc for doc in documents}

    def accesible_doc_ids(self) -> list[str]:
        user_id = self.request.state.user_id

        document_access = self.redis_service.hgetall(f"user:{user_id}:document_access")
        if document_access:
            return [
                k.decode() if isinstance(k, bytes) else k
                for k in document_access.keys()
                if (k.decode() if isinstance(k, bytes) else k).startswith("doc")
            ]

        db_document_access = self.document_access_repository.get_document_access_by_user_id(user_id)
        if db_document_access:
            document_access_dict = {}
            og_document_mapping = {}
            for document_access_item in db_document_access:
                document_access_dict[document_access_item.document_id] = "owner" if document_access_item.is_owner else "shared"

                if document_access_item.original_document_id:
                    document_access_dict[document_access_item.original_document_id] = "shared"
                    og_document_mapping[document_access_item.original_document_id] = document_access_item.document_id
                
            self.redis_service.hset(f"user:{user_id}:document_access", mapping=document_access_dict, ttl=60*60*24*5)
            self.redis_service.hset(f"user:{user_id}:og_document_mapping", mapping=og_document_mapping, ttl=60*60*24*5)

            return list(document_access_dict.keys())

        return []

    def get_document_by_id(self, document_id: str, include_images: bool = True):
        document = self.document_repository.get_document_by_id(document_id, include_images=include_images)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        return document

    def get_document_summary(self, document_id: str) -> str | None:
        document = self.document_repository.get_document_by_id(document_id, include_images=False)
        if not document or not getattr(document, "original_document_id", None):
            return None
        og_doc = self.original_document_repository.get_by_id(document.original_document_id)
        return og_doc.summary if og_doc else None
    
    def get_og_document_by_id(self, document_id: str):
        document = self.document_repository.get_document_by_original_id(document_id)
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
            status="new",
            images=[],
            markdown_parse_time=None,
        )
        self.redis_service.clear_user_cache(self.request.state.user_id)
        created_document = self.document_repository.create_document(document)
        return created_document

    def update_document(self, doc_id: str, update_document: UpdateDocumentRequest):
        document = self.document_repository.get_document_by_id(doc_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        if update_document.display_name:
            document.display_name = update_document.display_name
        document.updated_at = datetime.datetime.now()
        updated_document = self.document_repository.update_document(document)
        self.redis_service.clear_user_cache(self.request.state.user_id)
        if update_document.display_name:
            kafka.publish_document_display_name_changed(
                doc_id=document.document_id,
                old_name=document.display_name or "",
                new_name=update_document.display_name,
            )

        return updated_document

    def search_documents(self, query: str):
        return self.document_repository.search_documents_by_display_name( query)

    def delete_document(self, doc_id: str):
        document = self.document_repository.get_document_by_id(doc_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        og_doc_id = document.original_document_id
        self.document_access_request_repository.delete_requests_by_document_id(doc_id)
        self.document_access_repository.delete_all_by_document_id(doc_id)
        is_deleted = self.document_repository.delete_document(doc_id)
        if og_doc_id:
            og_repo = OriginalDocumentRepository(self.document_repository.db)
            new_count = og_repo.decrement_reference_counter(og_doc_id)
            if new_count is not None and new_count == 0:
                delete_vectors_by_doc_id(og_doc_id)
                og_repo.delete_by_id(og_doc_id)
        self.redis_service.clear_user_cache(self.request.state.user_id)
        self.redis_service.clear_document_cache(self.request.state.user_id, doc_id)
        return is_deleted

    async def ask_document(self, request: Request, doc_id: str, askDocumentRequest: AskDocumentRequest):
        document = self.get_document_by_id(doc_id)
        og_doc_id = document.original_document_id
        category = getattr(document, "category", None)
        sub_categories = getattr(document, "sub_categories", None)

        agentService = AgentService()
        start_time = time.perf_counter()
        try:
            result = await agentService.ask_the_rag(
                askDocumentRequest, og_doc_id, request,
                category=category, sub_categories=sub_categories,
            )
        except Exception as exc:
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=502, detail=f"LLM request failed: {exc}")
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

        ai_response = result.get("ai_response", "")
        reference_contents = result.get("reference_contents", [])

        # Publish Kafka event for async eval + billing (replaces background thread)
        user_email = None
        try:
            user_repo = UserRepository(self.document_repository.db)
            user = user_repo.get_user_by_id(self.request.state.user_id)
            if user:
                user_email = user.email_id
        except Exception:
            pass

        kafka.publish_ask_completed(
            user_id=self.request.state.user_id,
            doc_id=doc_id,
            result=result,
            latency_ms=latency_ms,
            user_email=user_email,
        )

        return {"ai_response": ai_response.strip(), "reference_contents": reference_contents}

    async def ask_document_stream(
        self,
        request: Request,
        doc_id: str,
        askDocumentRequest: AskDocumentRequest,
    ) -> AsyncGenerator[str, None]:
        """
        Async generator that produces SSE events for the streaming ask endpoint.
        Streams LLM tokens in real-time, then fires the background eval+persist
        thread after the final 'done' event.
        """
        import json

        document = self.get_document_by_id(doc_id)
        og_doc_id = getattr(document, "original_document_id", None) or ""
        category = getattr(document, "category", None)
        sub_categories = getattr(document, "sub_categories", None)

        agentService = AgentService()
        start_time = time.perf_counter()

        collected_tokens: list[str] = []
        final_done_payload: dict = {}
        internal_state: dict = {}

        try:
            async for sse_event_str in agentService.ask_the_rag_stream(
                askDocumentRequest, og_doc_id, request,
                category=category, sub_categories=sub_categories,
            ):
                lines = sse_event_str.strip().split("\n")
                event_type = lines[0].replace("event: ", "") if lines else ""
                data_line  = lines[1].replace("data: ", "") if len(lines) > 1 else "{}"

                try:
                    payload = json.loads(data_line)
                except Exception:
                    payload = {}

                if event_type == "_internal_state":
                    # Server-side only — capture for eval thread, do NOT forward to client
                    internal_state = payload
                    continue

                if event_type == "token":
                    collected_tokens.append(payload.get("content", ""))
                elif event_type == "done":
                    final_done_payload = payload

                yield sse_event_str

        except Exception as exc:
            import traceback
            traceback.print_exc()
            yield f"event: error\ndata: {json.dumps({'detail': 'Something went wrong. Please try again later.'})}\n\n"
            return

        # ── Publish Kafka event for async eval + billing ────────────────────
        latency_ms         = round((time.perf_counter() - start_time) * 1000, 2)
        ai_response        = "".join(collected_tokens)
        is_refusal         = final_done_payload.get("is_refusal", False)

        user_email = None
        try:
            user_repo  = UserRepository(self.document_repository.db)
            user       = user_repo.get_user_by_id(self.request.state.user_id)
            if user:
                user_email = user.email_id
        except Exception:
            pass

        logger.info(f"[ask_stream] Publishing Kafka event for doc={doc_id}, latency={latency_ms}ms, refusal={is_refusal}")
        kafka.publish_ask_stream_completed(
            user_id=self.request.state.user_id,
            doc_id=doc_id,
            ai_response=ai_response,
            internal_state=internal_state,
            is_refusal=is_refusal,
            latency_ms=latency_ms,
            user_email=user_email,
        )

    async def explain_word_text(self, request: Request, doc_id: str, explainWordDocumentRequest: ExplainWordDocumentRequest):
        document = self.get_document_by_id(doc_id)
        og_doc_id = document.original_document_id

        agentService = AgentService()
        start_time = time.perf_counter()

        try:
            result = await agentService.getWordExplanation(explainWordDocumentRequest, og_doc_id, request)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"LLM request failed: {exc}")

        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        ai_response = result.get("ai_response", "")
        reference_contents = result.get("reference_contents", [])

        user_email = None
        try:
            user_repo = UserRepository(self.document_repository.db)
            user = user_repo.get_user_by_id(self.request.state.user_id)
            if user:
                user_email = user.email_id
        except Exception:
            pass

        kafka.publish_explain_word_completed(
            user_id=self.request.state.user_id,
            doc_id=doc_id,
            word=explainWordDocumentRequest.word_to_explain,
            content_id=explainWordDocumentRequest.content_id,
            page_id=explainWordDocumentRequest.page_id,
            result=result,
            ai_response=ai_response,
            latency_ms=latency_ms,
            user_email=user_email,
        )

        return {"ai_response": ai_response.strip(), "reference_contents": reference_contents}

    async def explain_word_text_stream(
        self,
        request: Request,
        doc_id: str,
        explainWordDocumentRequest: ExplainWordDocumentRequest,
    ) -> AsyncGenerator[str, None]:
        """Async generator that produces SSE events for the streaming explain-word endpoint."""
        import json

        document = self.get_document_by_id(doc_id)
        og_doc_id = document.original_document_id

        agentService = AgentService()
        start_time = time.perf_counter()

        collected_tokens: list[str] = []
        final_done_payload: dict = {}
        internal_state: dict = {}

        try:
            async for sse_event_str in agentService.getWordExplanationStream(
                explainWordDocumentRequest, og_doc_id, request
            ):
                lines = sse_event_str.strip().split("\n")
                event_type = lines[0].replace("event: ", "") if lines else ""
                data_line  = lines[1].replace("data: ", "") if len(lines) > 1 else "{}"

                try:
                    payload = json.loads(data_line)
                except Exception:
                    payload = {}

                if event_type == "_internal_state":
                    internal_state = payload
                    continue

                if event_type == "token":
                    collected_tokens.append(payload.get("content", ""))
                elif event_type == "done":
                    final_done_payload = payload

                yield sse_event_str

        except Exception as exc:
            import traceback
            traceback.print_exc()
            yield f"event: error\ndata: {json.dumps({'detail': 'Something went wrong. Please try again later.'})}\n\n"
            return

        # ── Publish Kafka event for async eval + billing + persistence ────────
        latency_ms  = round((time.perf_counter() - start_time) * 1000, 2)
        ai_response = "".join(collected_tokens)

        user_email = None
        try:
            user_repo = UserRepository(self.document_repository.db)
            user = user_repo.get_user_by_id(self.request.state.user_id)
            if user:
                user_email = user.email_id
        except Exception:
            pass

        logger.info(f"[explain_word_stream] Publishing Kafka event for doc={doc_id}, word={explainWordDocumentRequest.word_to_explain}, latency={latency_ms}ms")
        kafka.publish_explain_word_stream_completed(
            user_id=self.request.state.user_id,
            doc_id=doc_id,
            word=explainWordDocumentRequest.word_to_explain,
            content_id=explainWordDocumentRequest.content_id,
            page_id=explainWordDocumentRequest.page_id,
            ai_response=ai_response,
            internal_state=internal_state,
            latency_ms=latency_ms,
            user_email=user_email,
        )
