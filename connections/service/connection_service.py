from connections.data.model import Connection
from connections.data.repository import ConnectionRepository
from ai_engine.data.qdrantRepository import QdrantRepository
from ai_engine.service.textEmbeddingService import TextEmbeddingService
from sqlalchemy.orm import Session
from fastapi import Request
import ulid
import datetime
import re


class ConnectionService:
    def __init__(self, db: Session, request: Request):
        self.repository = ConnectionRepository(db)
        self.request = request

    def get_or_create_connection(self, doc_id: str, content_id: int, text: str) -> Connection:
        existing = self.repository.get_connection(doc_id, content_id)
        if existing:
            return existing
        return self._fetch_and_store(doc_id, content_id, text)

    def refresh_connection(self, doc_id: str, content_id: int, text: str) -> Connection:
        existing = self.repository.get_connection(doc_id, content_id)
        if existing:
            chunks = self._search_vector_db(text)
            existing.source_text = text
            existing.connected_chunks = chunks
            return self.repository.update_connection(existing)
        return self._fetch_and_store(doc_id, content_id, text)

    def _fetch_and_store(self, doc_id: str, content_id: int, text: str) -> Connection:
        chunks = self._search_vector_db(text)
        connection = Connection(
            connection_id="conn_" + str(ulid.new()),
            doc_id=doc_id,
            content_id=content_id,
            source_text=text,
            connected_chunks=chunks,
            created_at=datetime.datetime.utcnow(),
            updated_at=datetime.datetime.utcnow(),
        )
        return self.repository.create_connection(connection)

    def _search_vector_db(self, text: str) -> list[dict]:
        accessible_docs = getattr(self.request.state, "accessible_documents", [])

        qdrant = QdrantRepository()
        embedding_service = TextEmbeddingService()

        dense_vector = embedding_service.embed_single_text(text)
        bm25_vector = embedding_service.bm25_embed_texts([text])[0]

        query_filter = {
            "must": [
                {
                    "key": "doc_id",
                    "match": {"any": accessible_docs},
                }
            ]
        }

        results = qdrant.search(
            dense_query_vector=dense_vector,
            bm25_query_vector=bm25_vector,
            query_filter=query_filter,
            top_k=5,
        )

        chunks = []
        contexts = results.get("contexts", [])
        sources = results.get("sources", [])

        # We need full payload data — re-search with payload access
        # The current search method only returns text+doc_id. Let's use a richer search.
        points = qdrant.client.query_points(
            collection_name=qdrant.collection,
            query=dense_vector,
            using="dense",
            query_filter=query_filter,
            with_payload=True,
            limit=5,
        ).points

        for point in points:
            payload = getattr(point, "payload", None) or {}
            clean_text = re.sub(r"\[SOURCE page .+ \| index .+\]","",payload.get("text", ""))
            chunks.append({
                "doc_id": payload.get("doc_id", ""),
                "text": clean_text,
                "start_page": payload.get("startPage", 0),
                "end_page": payload.get("endPage", 0),
                "start_content_index": payload.get("startContentIndex", 0),
                "end_content_index": payload.get("endContentIndex", 0),
            })

        return chunks
