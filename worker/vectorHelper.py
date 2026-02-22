from ai_engine.service.textEmbeddingService import TextEmbeddingService
from ai_engine.data.qdrantRepository import QdrantRepository
from ai_engine.service.connectionManager import ConnectionManager
from core.db_client import WorkerSessionLocal
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

    # --- Connections processing ---
    conn_manager = None
    own_db = db is None
    if own_db:
        db = WorkerSessionLocal()
    try:
        print("connections processing started")
        conn_manager = ConnectionManager(doc_id=doc_id, db=db)
        payloads = conn_manager.process_chunks(ids, dense_embeddings, payloads)
        print("connections processing ended")
    except Exception as e:
        print(f"[WARN] Connections processing failed, continuing without: {e}")

    # --- Qdrant upsert ---
    print("vector push started")
    QdrantRepository().upsert(ids, vectors, payloads)
    print("vector push ended")

    # --- Generate titles for connection groups ---
    if conn_manager:
        try:
            conn_manager.generate_titles(payloads)
        except Exception as e:
            print(f"[WARN] Connection title generation failed: {e}")

    if own_db:
        db.close()

    return True
