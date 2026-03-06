from documents.data.document.model import Document
from sqlalchemy.orm import Session
import json
import datetime
from typing import Any

from shared.redis import RedisService

# Default TTL for document cache (5 days)
DOC_CACHE_TTL = 60 * 60 * 24 * 5
NULLABLE_META_FIELDS = {"markdown_parse_time", "original_document_id"}


def _decode_redis_hash(meta: dict[str, Any] | None) -> dict[str, str] | None:
    """Decode bytes keys/values from Redis hgetall into str."""
    if not meta:
        return None
    return {
        (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
        for k, v in meta.items()
    }


def _serialize_doc_meta(doc: Any) -> dict[str, str]:
    """Serialize a document-like object (Document or DocumentRead) to cache meta dict."""
    return {
        "document_id": doc.document_id,
        "original_document_id": doc.original_document_id or "",
        "display_name": doc.display_name,
        "size_in_kilobyes": str(doc.size_in_kilobyes or 0),
        "created_at": doc.created_at.isoformat() if getattr(doc, "created_at", None) and hasattr(doc.created_at, "isoformat") else (str(doc.created_at) if getattr(doc, "created_at", None) else ""),
        "updated_at": doc.updated_at.isoformat() if getattr(doc, "updated_at", None) and hasattr(doc.updated_at, "isoformat") else (str(doc.updated_at) if getattr(doc, "updated_at", None) else ""),
        "is_deleted": str(getattr(doc, "is_deleted", False)),
        "status": doc.status or "new",
        "owner_id": doc.owner_id,
        "markdown_parse_time": str(doc.markdown_parse_time) if getattr(doc, "markdown_parse_time", None) is not None else "",
    }


class DocumentRead:
    """Read-only document view for cache hits. Same attribute shape as Document for API/serialization."""

    __slots__ = (
        "document_id", "original_document_id", "display_name", "size_in_kilobyes",
        "created_at", "updated_at", "is_deleted", "status", "owner_id",
        "images", "markdown_parse_time", "generated_title", "category", "sub_categories",
    )

    def __init__(
        self,
        document_id: str,
        original_document_id: str | None,
        display_name: str,
        size_in_kilobyes: float,
        created_at: datetime.datetime | str,
        updated_at: datetime.datetime | str,
        is_deleted: bool,
        status: str,
        owner_id: str,
        images: list[str] | None = None,
        markdown_parse_time: float | None = None,
    ):
        self.document_id = document_id
        self.original_document_id = original_document_id or None
        self.display_name = display_name
        self.size_in_kilobyes = float(size_in_kilobyes) if size_in_kilobyes is not None else 0.0
        if isinstance(created_at, str) and created_at:
            try:
                self.created_at = datetime.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except ValueError:
                self.created_at = datetime.datetime.now()
        else:
            self.created_at = created_at if isinstance(created_at, datetime.datetime) else datetime.datetime.now()
        if isinstance(updated_at, str) and updated_at:
            try:
                self.updated_at = datetime.datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            except ValueError:
                self.updated_at = datetime.datetime.now()
        else:
            self.updated_at = updated_at if isinstance(updated_at, datetime.datetime) else datetime.datetime.now()
        self.is_deleted = is_deleted if isinstance(is_deleted, bool) else (str(is_deleted).lower() == "true")
        self.status = status or "new"
        self.owner_id = owner_id
        self.images = images
        self.markdown_parse_time = float(markdown_parse_time) if markdown_parse_time not in (None, "") else None


def _doc_from_cache_meta(meta: dict[str, str], images: list[str] | None = None) -> DocumentRead:
    """Build DocumentRead from cached meta dict (and optional images list)."""
    normalized = dict(meta)
    for f in NULLABLE_META_FIELDS:
        if f in normalized and normalized[f] == "":
            normalized[f] = None
    return DocumentRead(
        document_id=normalized["document_id"],
        original_document_id=normalized.get("original_document_id"),
        display_name=normalized["display_name"],
        size_in_kilobyes=normalized.get("size_in_kilobyes", "0"),
        created_at=normalized.get("created_at", ""),
        updated_at=normalized.get("updated_at", ""),
        is_deleted=normalized.get("is_deleted", "false"),
        status=normalized.get("status", "new"),
        owner_id=normalized["owner_id"],
        images=images,
        markdown_parse_time=normalized.get("markdown_parse_time") or None,
    )


class DocumentRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_all_documents(self, all_doc_ids: list[str]):
        all_documents = self.db.query(Document).filter(Document.document_id.in_(all_doc_ids), Document.is_deleted == False).all()
        return all_documents

    def search_documents_by_display_name(self, query: str):
        return self.db.query(Document).filter(
            Document.is_deleted == False,
            Document.display_name.ilike(f"%{query}%")
        ).all()

    def get_document_by_id(self, document_id: str):
        return self.db.query(Document).filter(Document.document_id == document_id).first()

    def get_document_by_original_id(self, original_document_id: str):
        return self.db.query(Document).filter(
            Document.original_document_id == original_document_id,
            Document.is_deleted == False
        ).first()

    def create_document(self, document: Document):
        self.db.add(document)
        self.db.commit()
        self.db.refresh(document)
        return document

    def update_document(self, document: Document):
        self.db.commit()
        self.db.refresh(document)
        return document

    def delete_document(self, document: Document):
        self.db.delete(document)
        self.db.commit()
        return True

    def set_total_batches(self, document_id: str, total_batches: int):
        document = self.get_document_by_id(document_id)
        if document:
            document.total_batches = total_batches
            document.completed_batches = 0
            self.db.commit()
            return document
        return None

    def increment_completed_batches(self, document_id: str):
        document = self.get_document_by_id(document_id)
        if document:
            document.completed_batches = (document.completed_batches or 0) + 1
            self.db.commit()
            return document
        return None

    def set_status(self, document_id: str, status: str):
        document = self.get_document_by_id(document_id)
        if document:
            document.status = status
            self.db.commit()
            return document
        return None

    def update_final_job_status(self, document_id: str, status: str):
        document = self.get_document_by_id(document_id)
        if document:
            document.final_job_status = status
            self.db.commit()
            return document
        return None

    def is_all_batches_complete(self, document_id: str) -> bool:
        document = self.get_document_by_id(document_id)
        if document and document.total_batches:
            return (document.completed_batches or 0) >= document.total_batches
        return False

    def append_images(self, document_id: str, image_names: list[str]):
        document = self.get_document_by_id(document_id)
        if document:
            existing = document.images or []
            document.images = existing + image_names
            self.db.commit()
            return document
        return None


class CachedDocumentRepository:
    """
    Decorator around DocumentRepository that adds Redis cache-aside for reads
    and invalidates cache on writes. Service layer uses this instead of
    DocumentRepository so cache is transparent.
    """

    def __init__(self, inner: DocumentRepository, redis: RedisService):
        self._db_repo = inner
        self._redis = redis

    @property
    def db(self) -> Session:
        return self._db_repo.db

    def get_document_by_id(self, document_id: str, include_images: bool = True) -> Document | DocumentRead | None:
        meta_raw = self._redis.hgetall(f"doc:{document_id}:meta")
        meta = _decode_redis_hash(meta_raw)
        if meta:
            images = None
            if include_images:
                raw_images = self._redis.get_value(f"doc:{document_id}:images")
                if isinstance(raw_images, list):
                    images = raw_images
                elif isinstance(raw_images, str):
                    try:
                        images = json.loads(raw_images)
                    except (TypeError, json.JSONDecodeError):
                        images = None
                else:
                    images = raw_images  # already list from get_value json.loads
            return _doc_from_cache_meta(meta, images=images)
        document = self._db_repo.get_document_by_id(document_id)
        if not document:
            return None
        self._redis.set_doc_meta(document_id, _serialize_doc_meta(document), ttl=DOC_CACHE_TTL)
        self._redis.set_doc_images(document_id, document.images or [], ttl=DOC_CACHE_TTL)
        if not include_images:
            document.images = None
        return document

    def get_all_documents(
        self, all_doc_ids: list[str], include_images: bool = False
    ) -> list[Document | DocumentRead]:
        if not all_doc_ids:
            return []
        pipe = self._redis.pipeline()
        for doc_id in all_doc_ids:
            pipe.hgetall(f"doc:{doc_id}:meta")
        results = pipe.execute()
        doc_map: dict[str, Document | DocumentRead] = {}
        missing_ids: list[str] = []
        for doc_id, meta_raw in zip(all_doc_ids, results):
            meta = _decode_redis_hash(meta_raw)
            if meta:
                doc_map[doc_id] = _doc_from_cache_meta(meta, images=None)
            else:
                missing_ids.append(doc_id)
        if missing_ids:
            db_docs = self._db_repo.get_all_documents(missing_ids)
            for doc in db_docs:
                self._redis.set_doc_meta(doc.document_id, _serialize_doc_meta(doc), ttl=DOC_CACHE_TTL)
                self._redis.set_doc_images(doc.document_id, doc.images or [], ttl=DOC_CACHE_TTL)
                doc_map[doc.document_id] = doc
        if include_images:
            img_pipe = self._redis.pipeline()
            for doc_id in all_doc_ids:
                img_pipe.get(f"doc:{doc_id}:images")
            img_results = img_pipe.execute()
            for doc_id, raw in zip(all_doc_ids, img_results):
                doc = doc_map.get(doc_id)
                if doc is None:
                    continue
                if raw is not None:
                    val = raw.decode() if isinstance(raw, bytes) else raw
                    try:
                        images = json.loads(val) if isinstance(val, str) else val
                    except (TypeError, json.JSONDecodeError):
                        images = None
                else:
                    images = None
                if isinstance(doc, DocumentRead):
                    doc.images = images
                else:
                    doc.images = images
        return [doc_map[doc_id] for doc_id in all_doc_ids if doc_id in doc_map]

    def create_document(self, document: Document) -> Document:
        created = self._db_repo.create_document(document)
        self._redis.invalidate_doc_meta(created.document_id)
        return created

    def update_document(self, document: Document | DocumentRead) -> Document:
        if isinstance(document, DocumentRead):
            orm_doc = self._db_repo.get_document_by_id(document.document_id)
            if not orm_doc:
                raise ValueError(f"Document {document.document_id} not found for update")
            orm_doc.display_name = document.display_name
            orm_doc.updated_at = document.updated_at
            updated = self._db_repo.update_document(orm_doc)
        else:
            updated = self._db_repo.update_document(document)
        self._redis.invalidate_doc_meta(document.document_id)
        return updated

    def delete_document(self, document_id: str) -> bool:
        self._redis.invalidate_doc_meta(document_id)
        orm_doc = self._db_repo.get_document_by_id(document_id)
        if orm_doc is None:
            return False
        result = self._db_repo.delete_document(orm_doc)
        return result

    def set_total_batches(self, document_id: str, total_batches: int) -> Document | None:
        result = self._db_repo.set_total_batches(document_id, total_batches)
        if result:
            self._redis.invalidate_doc_meta(document_id)
        return result

    def increment_completed_batches(self, document_id: str) -> Document | None:
        result = self._db_repo.increment_completed_batches(document_id)
        if result:
            self._redis.invalidate_doc_meta(document_id)
        return result

    def set_status(self, document_id: str, status: str) -> Document | None:
        result = self._db_repo.set_status(document_id, status)
        if result:
            self._redis.invalidate_doc_meta(document_id)
        return result

    def update_final_job_status(self, document_id: str, status: str) -> Document | None:
        result = self._db_repo.update_final_job_status(document_id, status)
        if result:
            self._redis.invalidate_doc_meta(document_id)
        return result

    def append_images(self, document_id: str, image_names: list[str]) -> Document | None:
        result = self._db_repo.append_images(document_id, image_names)
        if result:
            self._redis.invalidate_doc_meta(document_id)
        return result

    def search_documents_by_display_name(self, query: str):
        return self._db_repo.search_documents_by_display_name(query)

    def get_document_by_original_id(self, original_document_id: str):
        return self._db_repo.get_document_by_original_id(original_document_id)

    def is_all_batches_complete(self, document_id: str) -> bool:
        return self._db_repo.is_all_batches_complete(document_id)
