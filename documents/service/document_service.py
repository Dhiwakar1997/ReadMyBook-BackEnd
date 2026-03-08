from documents.data.model import Document
from documents.data.repository import DocumentRepository, DocumentAccessRepository, DocumentAccessRequestRepository, CachedDocumentRepository
from documents.data.original_document.repository import OriginalDocumentRepository
from documents.data.schema import CreateDocumentRequest, UpdateDocumentRequest, AskDocumentRequest, ExplainWordDocumentRequest
from sqlalchemy.orm import Session
from fastapi import Request, HTTPException
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator
from ai_engine.service.agentService import AgentService
from ai_engine.graph.askGraph import eval_node
from dashboard.data.model import EvalRecord
from dashboard.data.repository import EvalRecordRepository
from users.data.repository import UserRepository
from shared.redis import RedisService
from core.db_client import SessionLocal
from worker.vectorHelper import delete_vectors_by_doc_id

import ulid
import json
import datetime
import time
import threading


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
            new_name = update_document.display_name
            doc_id = document.document_id

            def _propagate_display_name():
                from posts.data.repository import PostRepository
                db_session = SessionLocal()
                try:
                    PostRepository(db_session).update_display_name_for_doc(doc_id, new_name)
                except Exception as e:
                    print(f"[post_display_name] Failed to propagate display name: {e}")
                finally:
                    db_session.close()

            threading.Thread(target=_propagate_display_name, daemon=True).start()

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

        # Run eval + persist in background so the user gets the response immediately
        user_email = None
        try:
            user_repo = UserRepository(self.document_repository.db)
            user = user_repo.get_user_by_id(self.request.state.user_id)
            if user:
                user_email = user.email_id
        except Exception:
            pass

        def _background_eval():
            db_session = SessionLocal()
            try:
                eval_result = eval_node(result)
                eval_data = eval_result.get("evaluation") or {}
                node_costs = result.get("node_costs", []) + eval_result.get("node_costs", [])
                total_cost = eval_result.get("total_cost")

                record = EvalRecord(
                    document_id=doc_id,
                    user_email=user_email,
                    user_query=result.get("original_query", ""),
                    faithfulness=eval_data.get("faithfulness"),
                    response_relevancy=eval_data.get("response_relevancy"),
                    node_costs=node_costs,
                    total_cost=total_cost,
                    eval_cost=next((c["cost"] for c in node_costs if c["node"] == "eval_node"), 0),
                    latency_ms=latency_ms,
                    is_rag_retrieved=result.get("rag_context") is not None,
                    created_at=datetime.datetime.utcnow(),
                )
                EvalRecordRepository(db_session).create(record)

                # ── Billing deduction ──────────────────────────────────────────
                try:
                    from billing.service.balance_service import BalanceService
                    raw_cost = eval_result.get("total_cost") or 0.0
                    total_tokens = sum(c.get("total_tokens", 0) for c in result.get("node_costs", []))
                    billing = BalanceService(db_session)
                    billing.deduct_llm_cost(
                        user_id=request.state.user_id,
                        raw_cost_usd=raw_cost,
                        operation="ask",
                        document_id=doc_id,
                        token_count=total_tokens,
                    )
                except Exception as billing_exc:
                    print(f"[billing] ask deduct failed: {billing_exc}")
            except Exception as e:
                print(f"[eval_persist] Failed to save eval record: {e}")
            finally:
                db_session.close()

        threading.Thread(target=_background_eval, daemon=True).start()

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

        # ── Background: eval + persist ────────────────────────────────────────
        latency_ms         = round((time.perf_counter() - start_time) * 1000, 2)
        ai_response        = "".join(collected_tokens)
        reference_contents = final_done_payload.get("reference_contents", [])
        is_refusal         = final_done_payload.get("is_refusal", False)

        user_email = None
        try:
            user_repo  = UserRepository(self.document_repository.db)
            user       = user_repo.get_user_by_id(self.request.state.user_id)
            if user:
                user_email = user.email_id
        except Exception:
            pass

        def _background_eval():
            from ai_engine.graph.askGraph import eval_node
            from dashboard.data.model import EvalRecord
            from dashboard.data.repository import EvalRecordRepository

            mock_result = {
                "original_query":   internal_state.get("original_query", ""),
                "ai_response":      ai_response,
                "retrieval_chunks": internal_state.get("retrieval_chunks", []),
                "current_context":  "",
                "is_refusal":       is_refusal,
                "node_costs":       internal_state.get("node_costs", []),
                "rag_context":      internal_state.get("rag_context"),
            }
            db_session = SessionLocal()
            try:
                eval_result = eval_node(mock_result)
                eval_data   = eval_result.get("evaluation") or {}
                node_costs  = mock_result["node_costs"] + eval_result.get("node_costs", [])
                total_cost  = eval_result.get("total_cost")

                record = EvalRecord(
                    document_id        = doc_id,
                    user_email         = user_email,
                    user_query         = mock_result["original_query"],
                    faithfulness       = eval_data.get("faithfulness"),
                    response_relevancy = eval_data.get("response_relevancy"),
                    node_costs         = node_costs,
                    total_cost         = total_cost,
                    eval_cost          = next(
                        (c["cost"] for c in node_costs if c["node"] == "eval_node"), 0
                    ),
                    latency_ms         = latency_ms,
                    is_rag_retrieved   = True,
                    created_at         = datetime.datetime.utcnow(),
                )
                EvalRecordRepository(db_session).create(record)

                # ── Billing deduction ──────────────────────────────────────────
                try:
                    from billing.service.balance_service import BalanceService
                    raw_cost = eval_result.get("total_cost") or 0.0
                    print(raw_cost)
                    total_tokens = sum(c.get("total_tokens", 0) for c in mock_result.get("node_costs", []))
                    billing = BalanceService(db_session)
                    billing.deduct_llm_cost(
                        user_id=self.request.state.user_id,
                        raw_cost_usd=raw_cost,
                        operation="ask",
                        document_id=doc_id,
                        token_count=total_tokens,
                    )
                except Exception as billing_exc:
                    print(f"[billing] ask stream deduct failed: {billing_exc}")
            except Exception as e:
                print(f"[eval_persist] SSE stream: Failed to save eval record: {e}")
            finally:
                db_session.close()

        threading.Thread(target=_background_eval, daemon=True).start()

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

        def _background_eval():
            from ai_engine.graph.askGraph import eval_node
            from dashboard.data.model import EvalRecord
            from dashboard.data.repository import EvalRecordRepository
            mock_result = {
                "original_query":   result.get("word_to_explain", ""),
                "ai_response":      ai_response,
                "retrieval_chunks": [],
                "current_context":  "",
                "is_refusal":       result.get("is_refusal", False),
                "node_costs":       result.get("node_costs", []),
                "rag_context":      result.get("rag_context"),
            }
            db_session = SessionLocal()
            try:
                eval_result = eval_node(mock_result)
                eval_data   = eval_result.get("evaluation") or {}
                node_costs  = mock_result["node_costs"] + eval_result.get("node_costs", [])
                record = EvalRecord(
                    document_id        = doc_id,
                    user_email         = user_email,
                    user_query         = mock_result["original_query"],
                    faithfulness       = eval_data.get("faithfulness"),
                    response_relevancy = eval_data.get("response_relevancy"),
                    node_costs         = node_costs,
                    total_cost         = eval_result.get("total_cost"),
                    eval_cost          = next((c["cost"] for c in node_costs if c["node"] == "eval_node"), 0),
                    latency_ms         = latency_ms,
                    is_rag_retrieved   = result.get("rag_context") is not None,
                    created_at         = datetime.datetime.utcnow(),
                )
                EvalRecordRepository(db_session).create(record)

                # ── Billing deduction ──────────────────────────────────────────
                try:
                    from billing.service.balance_service import BalanceService
                    raw_cost = eval_result.get("total_cost") or 0.0
                    total_tokens = sum(c.get("total_tokens", 0) for c in mock_result.get("node_costs", []))
                    billing = BalanceService(db_session)
                    billing.deduct_llm_cost(
                        user_id=request.state.user_id,
                        raw_cost_usd=raw_cost,
                        operation="explain_word",
                        document_id=doc_id,
                        token_count=total_tokens,
                    )
                except Exception as billing_exc:
                    print(f"[billing] explain-word deduct failed: {billing_exc}")

                # ── Persist word explanation ───────────────────────────────────
                try:
                    from word_explanations.data.model import WordExplanation
                    from word_explanations.data.repository import WordExplanationRepository
                    import ulid as _ulid
                    explanation = WordExplanation(
                        explanation_id="wexp_" + str(_ulid.new()),
                        doc_id=doc_id,
                        user_id=request.state.user_id,
                        word=explainWordDocumentRequest.word_to_explain,
                        content_id=explainWordDocumentRequest.content_id,
                        page_id=explainWordDocumentRequest.page_id,
                        ai_explanation=ai_response.strip(),
                        created_at=datetime.datetime.utcnow(),
                    )
                    WordExplanationRepository(db_session).create(explanation)
                except Exception as wexp_exc:
                    print(f"[word_explanation] explain-word persist failed: {wexp_exc}")
            except Exception as e:
                print(f"[eval_persist] explain-word: Failed to save eval record: {e}")
            finally:
                db_session.close()

        threading.Thread(target=_background_eval, daemon=True).start()

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

        # ── Background: eval + persist ────────────────────────────────────────
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

        def _background_eval():
            from ai_engine.graph.askGraph import eval_node
            from dashboard.data.model import EvalRecord
            from dashboard.data.repository import EvalRecordRepository
            mock_result = {
                "original_query":   internal_state.get("word_to_explain", ""),
                "ai_response":      ai_response,
                "retrieval_chunks": [],
                "current_context":  "",
                "is_refusal":       internal_state.get("is_refusal", False),
                "node_costs":       internal_state.get("node_costs", []),
                "rag_context":      internal_state.get("rag_context"),
            }
            db_session = SessionLocal()
            try:
                eval_result = eval_node(mock_result)
                eval_data   = eval_result.get("evaluation") or {}
                node_costs  = mock_result["node_costs"] + eval_result.get("node_costs", [])
                record = EvalRecord(
                    document_id        = doc_id,
                    user_email         = user_email,
                    user_query         = mock_result["original_query"],
                    faithfulness       = eval_data.get("faithfulness"),
                    response_relevancy = eval_data.get("response_relevancy"),
                    node_costs         = node_costs,
                    total_cost         = eval_result.get("total_cost"),
                    eval_cost          = next((c["cost"] for c in node_costs if c["node"] == "eval_node"), 0),
                    latency_ms         = latency_ms,
                    is_rag_retrieved   = internal_state.get("rag_context") is not None,
                    created_at         = datetime.datetime.utcnow(),
                )
                EvalRecordRepository(db_session).create(record)

                # ── Billing deduction ──────────────────────────────────────────
                try:
                    raw_cost = eval_result.get("total_cost") or 0.0
                    total_tokens = sum(c.get("total_tokens", 0) for c in mock_result.get("node_costs", []))
                    billing = BalanceService(db_session)
                    billing.deduct_llm_cost(
                        user_id=self.request.state.user_id,
                        raw_cost_usd=raw_cost,
                        operation="explain_word",
                        document_id=doc_id,
                        token_count=total_tokens,
                    )
                except Exception as billing_exc:
                    print(f"[billing] explain-word stream deduct failed: {billing_exc}")

                # ── Persist word explanation ───────────────────────────────────
                try:
                    from word_explanations.data.model import WordExplanation
                    from word_explanations.data.repository import WordExplanationRepository
                    import ulid as _ulid
                    explanation = WordExplanation(
                        explanation_id="wexp_" + str(_ulid.new()),
                        doc_id=doc_id,
                        user_id=self.request.state.user_id,
                        word=explainWordDocumentRequest.word_to_explain,
                        content_id=explainWordDocumentRequest.content_id,
                        page_id=explainWordDocumentRequest.page_id,
                        ai_explanation=ai_response.strip(),
                        created_at=datetime.datetime.utcnow(),
                    )
                    WordExplanationRepository(db_session).create(explanation)
                except Exception as wexp_exc:
                    print(f"[word_explanation] explain-word stream persist failed: {wexp_exc}")
            except Exception as e:
                print(f"[eval_persist] explain-word stream: Failed to save eval record: {e}")
            finally:
                db_session.close()

        threading.Thread(target=_background_eval, daemon=True).start()
