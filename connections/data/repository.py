from connections.data.model import Connection
from sqlalchemy.orm import Session
import datetime


class ConnectionRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_connection(self, doc_id: str, content_id: int) -> Connection | None:
        return (
            self.db.query(Connection)
            .filter(
                Connection.doc_id == doc_id,
                Connection.content_id == content_id,
            )
            .first()
        )

    def create_connection(self, connection: Connection) -> Connection:
        self.db.add(connection)
        self.db.commit()
        self.db.refresh(connection)
        return connection

    def update_connection(self, connection: Connection) -> Connection:
        connection.updated_at = datetime.datetime.utcnow()
        self.db.commit()
        self.db.refresh(connection)
        return connection
