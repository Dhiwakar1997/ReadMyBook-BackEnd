from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct
import os

class QdrantStorage:
    def __init__(self, collection="docs", dim=3072):
        self.url = os.getenv("QDRANT_URL", "http://localhost:6333")
        self.client = QdrantClient(url=self.url, api_key=os.getenv("QDRANT_KEY",None), timeout=30)
        self.collection = collection
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )

    def upsert(self, ids, vectors, payloads, batch_size=100):
        """Upsert vectors in batches to avoid Qdrant payload size limits (32MB).
        
        Args:
            ids: List of point IDs
            vectors: List of vectors
            payloads: List of payload dicts
            batch_size: Number of points per batch (default 100)
        """
        total = len(ids)
        for start in range(0, total, batch_size):
            end = min(start + batch_size, total)
            batch_points = [
                PointStruct(id=ids[i], vector=vectors[i], payload=payloads[i])
                for i in range(start, end)
            ]
            self.client.upsert(self.collection, points=batch_points)
            print(f"Upserted batch {start // batch_size + 1}/{(total + batch_size - 1) // batch_size} ({end - start} points)")

    def search(self, query_vector, query_filter=None, top_k: int = 5):
        results = self.client.query_points(
            collection_name=self.collection,
            query=query_vector,
            query_filter=query_filter,
            with_payload=True,
            limit=top_k
        ).points
        contexts = []
        sources = set()

        for r in results:
            payload = getattr(r, "payload", None) or {}
            text = payload.get("text", "")
            source = payload.get("doc_id", "")
            if text:
                contexts.append(text)
                sources.add(source)

        return {"contexts": contexts, "sources": list(sources)}