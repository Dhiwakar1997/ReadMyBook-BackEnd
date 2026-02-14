from ai_engine.service.textEmbeddingService import TextEmbeddingService
from ai_engine.data.qdrantRepository import QdrantRepository
import uuid

def push_data_to_vector_db(metadata: dict, doc_id: str, user_id: str) -> bool:
    text_embedding_service = TextEmbeddingService()
    texts, payloads = text_embedding_service.load_chunk(metadata)
    payloads = [{"doc_id": doc_id, "owner_id": user_id, **p} for p in payloads]
    print("embeddings started")

    vectors = {"dense":text_embedding_service.dense_embed_texts(texts),
                "bm25":text_embedding_service.bm25_embed_texts(texts)}
                
    ids = [str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc_id}:{i}")) for i in range(len(texts))]
    print(f"embeddings ended vectors: {len(vectors)} payloads: {len(payloads)} ids: {len(ids)}")
    
    print("vector push started")
    QdrantRepository().upsert(ids, vectors, payloads)
    print("vector push ended")    
    return True