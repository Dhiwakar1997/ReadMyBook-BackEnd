import math
import uuid
import json
from openai import OpenAI
from sqlalchemy.orm import Session
from ai_engine.data.qdrantRepository import QdrantRepository
from connections.data.repository import ConnectionRepository
from qdrant_client.models import PointStruct

DENSITY_THRESHOLD = 0.33
CONNECTION_THRESHOLD = 0.72
CONNECTION_CAPACITY = 50
ANN_TOP_K = 5
EMBED_DIM = 3072

TITLE_MODEL = "gpt-4.1-mini"


class ConnectionManager:
    """
    Manages semantic connection groups across documents.
    Inserted into the pipeline after embedding generation, before Qdrant upsert.
    """

    def __init__(self, doc_id: str, db: Session):
        self.doc_id = doc_id
        self.db = db
        self.conn_repo = ConnectionRepository(db)
        self.centroid_qdrant = QdrantRepository(
            collection="connections", dim=EMBED_DIM, sparse=False, quantize=False
        )
        self._affected_connections: set[str] = set()
        self._load_corpus_state()

    def _load_corpus_state(self):
        """Load existing corpus_mean and chunk_count from PostgreSQL."""
        state = self.conn_repo.get_corpus_state(self.doc_id)
        if state:
            self.corpus_mean = state.corpus_mean_vector
            self.corpus_count = state.chunk_count
        else:
            self.corpus_mean = None
            self.corpus_count = 0

    @staticmethod
    def _normalize(vec: list[float]) -> list[float]:
        """L2-normalize a vector."""
        norm = math.sqrt(sum(x * x for x in vec))
        if norm < 1e-12:
            return vec
        return [x / norm for x in vec]

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Cosine similarity between two L2-normalized vectors (= dot product)."""
        return sum(x * y for x, y in zip(a, b))

    @staticmethod
    def _update_mean_incremental(
        old_mean: list[float], new_vec: list[float], n: int
    ) -> list[float]:
        """Welford-style incremental mean update, then normalize."""
        inv_n = 1.0 / n
        updated = [
            old_mean[i] + (new_vec[i] - old_mean[i]) * inv_n
            for i in range(len(old_mean))
        ]
        norm = math.sqrt(sum(x * x for x in updated))
        if norm < 1e-12:
            return updated
        return [x / norm for x in updated]

    def process_chunks(
        self,
        chunk_ids: list[str],
        dense_embeddings: list[list[float]],
        payloads: list[dict],
    ) -> list[dict]:
        """
        Process all chunks for a document. Mutates payloads in-place to add
        connection metadata (connection_id, density_score, similarity_score).
        Returns the payloads.
        """
        for idx, embedding in enumerate(dense_embeddings):
            normed = self._normalize(embedding)

            # --- Update corpus mean ---
            self.corpus_count += 1
            if self.corpus_mean is None:
                self.corpus_mean = normed
            else:
                self.corpus_mean = self._update_mean_incremental(
                    self.corpus_mean, normed, self.corpus_count
                )

            # --- Density score (richness filter) ---
            density_score = 1.0 - self._cosine_similarity(normed, self.corpus_mean)

            if density_score < DENSITY_THRESHOLD:
                payloads[idx]["connection_id"] = None
                payloads[idx]["density_score"] = round(density_score, 6)
                payloads[idx]["similarity_score"] = None
                continue

            # --- ANN search against existing centroids ---
            connection_id, similarity = self._find_nearest_connection(normed)

            if connection_id and similarity > CONNECTION_THRESHOLD:
                group = self.conn_repo.get_connection_group(connection_id)
                if group and group.chunk_count >= CONNECTION_CAPACITY:
                    # Capacity exceeded — create sibling group
                    connection_id, similarity = self._create_connection_group(
                        normed, parent_id=connection_id
                    )
                else:
                    # Assign to existing group and update centroid
                    new_count = (group.chunk_count if group else 0) + 1
                    self._update_connection_centroid(
                        connection_id, normed, new_count
                    )
                    self.conn_repo.increment_chunk_count(connection_id)
            else:
                # No suitable match — create new group
                connection_id, similarity = self._create_connection_group(normed)

            self._affected_connections.add(connection_id)
            payloads[idx]["connection_id"] = connection_id
            payloads[idx]["density_score"] = round(density_score, 6)
            payloads[idx]["similarity_score"] = round(similarity, 6)

        # --- Persist corpus state ---
        self.conn_repo.upsert_corpus_state(
            self.doc_id, self.corpus_mean, self.corpus_count
        )
        self.db.commit()

        print(
            f"[Connections] Processed {len(dense_embeddings)} chunks, "
            f"{len(self._affected_connections)} connection groups affected"
        )
        return payloads

    def generate_titles(self, payloads: list[dict]):
        """
        Generate LLM titles and descriptions for all connection groups
        that were created or updated during this run.
        """
        if not self._affected_connections:
            return

        # Gather chunk texts per connection
        texts_by_conn: dict[str, list[str]] = {}
        for p in payloads:
            conn_id = p.get("connection_id")
            if conn_id and conn_id in self._affected_connections:
                text = p.get("text", "")
                if text:
                    if conn_id not in texts_by_conn:
                        texts_by_conn[conn_id] = []
                    texts_by_conn[conn_id].append(text)

        if not texts_by_conn:
            return

        # Build a single LLM request with all connection groups
        groups_for_llm = []
        for conn_id, texts in texts_by_conn.items():
            # Take up to 5 representative chunks (first, last, and middle samples)
            sample = _sample_texts(texts, max_samples=5)
            groups_for_llm.append(
                {"connection_id": conn_id, "chunks": sample}
            )

        print(f"[Connections] Generating titles for {len(groups_for_llm)} connection groups")

        prompt = (
            "You are given groups of text chunks from a document. Each group is a semantic cluster.\n"
            "For each group, generate:\n"
            "- title: A concise title (max 8 words) capturing the common theme\n"
            "- description: A brief description (1-2 sentences) of what the chunks cover\n\n"
            "Return a JSON array with objects: {\"connection_id\": \"...\", \"title\": \"...\", \"description\": \"...\"}\n"
            "Return ONLY the JSON array, no other text.\n\n"
        )

        for g in groups_for_llm:
            prompt += f"--- Group {g['connection_id']} ---\n"
            for chunk in g["chunks"]:
                # Truncate each chunk to ~300 chars to stay within token limits
                truncated = chunk[:300] + "..." if len(chunk) > 300 else chunk
                prompt += f"{truncated}\n\n"

        try:
            client = OpenAI()
            response = client.chat.completions.create(
                model=TITLE_MODEL,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )

            content = response.choices[0].message.content.strip()
            # Strip markdown code fences if present
            if content.startswith("```"):
                content = content.split("\n", 1)[1] if "\n" in content else content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()

            results = json.loads(content)

            for item in results:
                conn_id = item.get("connection_id")
                title = item.get("title", "")
                description = item.get("description", "")
                if conn_id and conn_id in self._affected_connections:
                    self.conn_repo.update_title_and_description(
                        conn_id, title, description
                    )

            self.db.commit()
            print(f"[Connections] Titles generated for {len(results)} groups")

        except Exception as e:
            print(f"[WARN] Title generation failed: {e}")

    def _find_nearest_connection(
        self, normed_embedding: list[float]
    ) -> tuple[str | None, float]:
        """ANN search in the connections Qdrant collection (global, no doc filter)."""
        try:
            results = self.centroid_qdrant.client.query_points(
                collection_name="connections",
                query=normed_embedding,
                using="dense",
                with_payload=True,
                limit=ANN_TOP_K,
            ).points

            if not results:
                return None, 0.0

            best = results[0]
            return best.payload.get("connection_id"), best.score

        except Exception:
            return None, 0.0

    def _create_connection_group(
        self, normed_embedding: list[float], parent_id: str = None
    ) -> tuple[str, float]:
        """Create a new connection group with this chunk as the initial centroid."""
        connection_id = str(uuid.uuid4())
        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"conn:{connection_id}"))

        self.centroid_qdrant.client.upsert(
            collection_name="connections",
            points=[
                PointStruct(
                    id=point_id,
                    vector={"dense": normed_embedding},
                    payload={
                        "connection_id": connection_id,
                        "parent_id": parent_id,
                    },
                )
            ],
        )

        self.conn_repo.create_connection_group(
            connection_id=connection_id,
            parent_id=parent_id,
            initial_chunk_count=1,
        )

        return connection_id, 1.0

    def _update_connection_centroid(
        self, connection_id: str, normed_embedding: list[float], new_count: int
    ):
        """Incrementally update the centroid vector in Qdrant."""
        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"conn:{connection_id}"))

        points = self.centroid_qdrant.client.retrieve(
            collection_name="connections",
            ids=[point_id],
            with_vectors=True,
        )
        if not points:
            return

        old_centroid = points[0].vector["dense"]
        new_centroid = self._update_mean_incremental(
            old_centroid, normed_embedding, new_count
        )

        self.centroid_qdrant.client.upsert(
            collection_name="connections",
            points=[
                PointStruct(
                    id=point_id,
                    vector={"dense": new_centroid},
                    payload=points[0].payload,
                )
            ],
        )


def _sample_texts(texts: list[str], max_samples: int = 5) -> list[str]:
    """Select representative samples from a list of texts."""
    if len(texts) <= max_samples:
        return texts
    # Take first, last, and evenly spaced middle samples
    indices = [0]
    step = (len(texts) - 1) / (max_samples - 1)
    for i in range(1, max_samples - 1):
        indices.append(round(i * step))
    indices.append(len(texts) - 1)
    return [texts[i] for i in indices]
