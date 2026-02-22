from sqlalchemy.orm import Session
from connections.data.model import ConnectionGroup, DocumentCorpusState
import uuid
import datetime


class ConnectionRepository:
    def __init__(self, db: Session):
        self.db = db

    # --- Corpus State ---

    def get_corpus_state(self, doc_id: str) -> DocumentCorpusState | None:
        return (
            self.db.query(DocumentCorpusState)
            .filter(DocumentCorpusState.doc_id == doc_id)
            .first()
        )

    def upsert_corpus_state(
        self, doc_id: str, corpus_mean: list[float], chunk_count: int
    ):
        state = self.get_corpus_state(doc_id)
        if state:
            state.corpus_mean_vector = corpus_mean
            state.chunk_count = chunk_count
            state.updated_at = datetime.datetime.utcnow()
        else:
            state = DocumentCorpusState(
                id=str(uuid.uuid4()),
                doc_id=doc_id,
                corpus_mean_vector=corpus_mean,
                chunk_count=chunk_count,
            )
            self.db.add(state)

    # --- Connection Groups ---

    def get_connection_group(self, connection_id: str) -> ConnectionGroup | None:
        return (
            self.db.query(ConnectionGroup)
            .filter(ConnectionGroup.connection_id == connection_id)
            .first()
        )

    def create_connection_group(
        self,
        connection_id: str,
        parent_id: str = None,
        initial_chunk_count: int = 1,
    ):
        group = ConnectionGroup(
            connection_id=connection_id,
            parent_id=parent_id,
            chunk_count=initial_chunk_count,
        )
        self.db.add(group)

    def increment_chunk_count(self, connection_id: str):
        group = self.get_connection_group(connection_id)
        if group:
            group.chunk_count = (group.chunk_count or 0) + 1
            group.updated_at = datetime.datetime.utcnow()

    def update_title_and_description(
        self, connection_id: str, title: str, description: str
    ):
        group = self.get_connection_group(connection_id)
        if group:
            group.title = title
            group.description = description
            group.updated_at = datetime.datetime.utcnow()
