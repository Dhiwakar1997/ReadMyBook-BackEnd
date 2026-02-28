from fastembed import sparse
from qdrant_client import QdrantClient
from qdrant_client.models import *
import os

class QdrantRepository:
    
    def __init__(self, collection="docs", dim=3072, sparse=True, quantize=True):
        self.url = os.getenv("QDRANT_URL", "http://localhost:6333")
        self.client = QdrantClient(url=self.url, api_key=os.getenv("QDRANT_KEY", None), timeout=30)
        self.collection = collection
        self.quantize = quantize
        self.dim = dim

        self.create_collection_if_not_exists()
       

    def create_collection_if_not_exists(self):
        if not self.client.collection_exists(self.collection):
                    vectors_config = {"dense": VectorParams(size=self.dim, distance=Distance.COSINE)}
                    sparse_config = {"bm25": SparseVectorParams()} if sparse else None
                    quant_config = (
                        ScalarQuantization(
                            scalar=ScalarQuantizationConfig(
                                type=ScalarType.INT8, quantile=0.99, always_ram=True
                            )
                        )
                        if self.quantize
                        else None
                    )

                    self.client.create_collection(
                        collection_name=self.collection,
                        vectors_config=vectors_config,
                        sparse_vectors_config=sparse_config,
                        quantization_config=quant_config,
                    )
                    # Create payload indexes for filtering
                    self.client.create_payload_index(
                        collection_name=self.collection,
                        field_name="doc_id",
                        field_schema=PayloadSchemaType.KEYWORD,
                    )

    def upsert(self, ids, vectors, payloads, batch_size=100):
        """Upsert vectors in batches to avoid Qdrant payload size limits (32MB)."""
        total = len(ids)
        for start in range(0, total, batch_size):
            end = min(start + batch_size, total)
            batch_points = []
            for i in range(start, end):
                bothVector = {"dense": vectors["dense"][i],
                    "bm25": SparseVector(indices=vectors["bm25"][i].indices.tolist(),
                                        values=vectors["bm25"][i].values.tolist(),),}
                batch_points.append(
                    PointStruct(id=ids[i], vector=bothVector, payload=payloads[i]))
                    

            self.client.upsert(self.collection, points=batch_points)
            print(f"Upserted batch {start // batch_size + 1}/{(total + batch_size - 1) // batch_size} ({end - start} points)")

    def search(self, dense_query_vector, bm25_query_vector, query_filter=None, top_k: int = 20, alpha=None,score_threshold=0.0):
        bm25_query_vector = SparseVector(
            indices=bm25_query_vector.indices.tolist(),
            values=bm25_query_vector.values.tolist(),
        )

        if alpha:
            dense_results = self.client.query_points(
                collection_name=self.collection,
                query=dense_query_vector,
                using="dense",
                query_filter=query_filter,
                with_payload=True,
                score_threshold=score_threshold,
                limit=top_k,
            ).points

            sparse_results = self.client.query_points(
                collection_name=self.collection,
                query=bm25_query_vector,
                using="bm25",
                query_filter=query_filter,
                with_payload=True,
                score_threshold=score_threshold,
                limit=top_k,
            ).points

            # Merge by point ID with weighted scores
            scores = {}
            point_map = {}
            for r in dense_results:
                scores[r.id] = alpha * (r.score or 0)
                point_map[r.id] = r
            for r in sparse_results:
                scores[r.id] = scores.get(r.id, 0) + (1 - alpha) * (r.score or 0)
                if r.id not in point_map:
                    point_map[r.id] = r

            ranked_ids = sorted(scores, key=scores.get, reverse=True)[:top_k]
            results = [point_map[pid] for pid in ranked_ids]
        else:
            results = self.client.query_points(
                collection_name=self.collection,
                query=FusionQuery(fusion=Fusion.RRF),
                prefetch=[
                    Prefetch(query=dense_query_vector, using="dense", limit=30),
                    Prefetch(query=bm25_query_vector, using="bm25", limit=30),
                ],
                query_filter=query_filter,
                with_payload=True,
                score_threshold=score_threshold,
                limit=top_k,
            ).points

        contexts = []
        sources = []
        payloads = []

        for r in results:
            payload = getattr(r, "payload", None) or {}
            payloads.append(payload)
            text = payload.get("text", "")
            source = payload.get("doc_id", "")
            if text:
                contexts.append(text)
                sources.append(source)

        return {"contexts": contexts, "sources": sources, "payloads":payloads}

    def scroll_by_filter(self, query_filter, limit: int = 100, with_payload=True):
        """Scroll through points matching a filter. Returns list of points."""
        all_points = []
        offset = None
        while True:
            results, next_offset = self.client.scroll(
                collection_name=self.collection,
                scroll_filter=query_filter,
                limit=limit,
                offset=offset,
                with_payload=with_payload,
                with_vectors=False,
            )
            all_points.extend(results)
            if next_offset is None:
                break
            offset = next_offset
        return all_points
