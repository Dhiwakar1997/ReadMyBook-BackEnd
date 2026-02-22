from fastapi import APIRouter, Depends, HTTPException
from middleware import verify_access_token
from core.db_client import get_db
from sqlalchemy.orm import Session
from ai_engine.data.qdrantRepository import QdrantRepository
from connections.data.repository import ConnectionRepository
from qdrant_client.models import FieldCondition, MatchValue, Filter, IsNullCondition, PayloadField

connection_router = APIRouter(prefix="/connections", tags=["connections"])


@connection_router.get("/document/{doc_id}", dependencies=[Depends(verify_access_token)])
def get_connections_for_document(doc_id: str, db: Session = Depends(get_db)):
    """
    Get all connection groups that contain chunks from a given document.
    Returns unique connection IDs with their title and description.
    """
    try:
        qdrant = QdrantRepository()

        # Scroll all chunks for this doc_id that have a non-null connection_id
        points = qdrant.scroll_by_filter(
            query_filter=Filter(
                must=[
                    FieldCondition(key="doc_id", match=MatchValue(value=doc_id)),
                ],
                must_not=[
                    IsNullCondition(is_null=PayloadField(key="connection_id")),
                ],
            ),
        )

        # Collect unique connection IDs
        connection_ids = set()
        for point in points:
            payload = getattr(point, "payload", None) or {}
            conn_id = payload.get("connection_id")
            if conn_id:
                connection_ids.add(conn_id)

        if not connection_ids:
            return {"connections": [], "doc_id": doc_id}

        # Fetch connection metadata from PostgreSQL
        conn_repo = ConnectionRepository(db)
        connections = []
        for conn_id in connection_ids:
            group = conn_repo.get_connection_group(conn_id)
            if group:
                connections.append({
                    "connection_id": group.connection_id,
                    "title": group.title,
                    "description": group.description,
                    "chunk_count": group.chunk_count,
                    "parent_id": group.parent_id,
                })

        return {"connections": connections, "doc_id": doc_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@connection_router.get("/{connection_id}", dependencies=[Depends(verify_access_token)])
def get_connection_details(connection_id: str, db: Session = Depends(get_db)):
    """
    Get all chunks belonging to a connection group.
    Returns a flat list with one entry per content_id, expanded from
    each chunk's startContentIndex..endContentIndex range.
    """
    try:
        conn_repo = ConnectionRepository(db)
        group = conn_repo.get_connection_group(connection_id)
        if not group:
            raise HTTPException(status_code=404, detail="Connection not found")

        qdrant = QdrantRepository()

        points = qdrant.scroll_by_filter(
            query_filter=Filter(
                must=[
                    FieldCondition(
                        key="connection_id", match=MatchValue(value=connection_id)
                    ),
                ],
            ),
        )

        result = []
        for point in points:
            payload = getattr(point, "payload", None) or {}
            doc_id = payload.get("doc_id", "")
            chunk_id = str(point.id)
            start = payload.get("startContentIndex")
            end = payload.get("endContentIndex")

            if start is not None and end is not None:
                for content_id in range(int(start), int(end) + 1):
                    result.append({
                        "doc_id": doc_id,
                        "connection_id": connection_id,
                        "chunk_id": chunk_id,
                        "content_id": content_id,
                    })

        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
