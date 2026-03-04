from ai_engine.service.textEmbeddingService import TextEmbeddingService
from ai_engine.data.qdrantRepository import QdrantRepository
from qdrant_client.models import FieldCondition, MatchValue, Filter
import uuid


def push_data_to_vector_db(metadata: dict, doc_id: str, user_id: str, db=None) -> bool:
    text_embedding_service = TextEmbeddingService()
    texts, payloads = text_embedding_service.load_chunk(metadata)
    payloads = [{"doc_id": doc_id, "owner_id": user_id, **p} for p in payloads]
    print("embeddings started")

    dense_embeddings = text_embedding_service.dense_embed_texts(texts)
    sparse_embeddings = text_embedding_service.bm25_embed_texts(texts)
    vectors = {"dense": dense_embeddings, "bm25": sparse_embeddings}

    ids = [str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc_id}:{i}")) for i in range(len(texts))]
    print(f"embeddings ended vectors: {len(vectors)} payloads: {len(payloads)} ids: {len(ids)}")

    # --- Qdrant upsert ---
    print("vector push started")
    QdrantRepository().upsert(ids, vectors, payloads)
    print("vector push ended")

    return True


def delete_vectors_by_doc_id(doc_id: str):
    """Delete all vectors with the given doc_id from Qdrant."""
    qdrant = QdrantRepository()
    query_filter = Filter(must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))])
    points = qdrant.scroll_by_filter(query_filter, with_payload=False)
    if not points:
        print(f"No vectors found for doc_id={doc_id}")
        return
    point_ids = [p.id for p in points]
    qdrant.client.delete(collection_name=qdrant.collection, points_selector=point_ids)
    print(f"Deleted {len(point_ids)} vectors for doc_id={doc_id}")


def update_vector_doc_ids(old_doc_id: str, new_og_doc_id: str):
    """Update doc_id payload from old_doc_id to new_og_doc_id for all matching vectors."""
    qdrant = QdrantRepository()
    query_filter = Filter(must=[FieldCondition(key="doc_id", match=MatchValue(value=old_doc_id))])
    points = qdrant.scroll_by_filter(query_filter, with_payload=False)
    if not points:
        print(f"No vectors found for doc_id={old_doc_id}")
        return
    point_ids = [p.id for p in points]
    qdrant.client.set_payload(
        collection_name=qdrant.collection,
        payload={"doc_id": new_og_doc_id},
        points=point_ids,
    )
    print(f"Updated {len(point_ids)} vectors: doc_id {old_doc_id} -> {new_og_doc_id}")
