# Re-export all document-related repositories.
from documents.data.document.repository import (
    DocumentRepository,
    CachedDocumentRepository,
    DocumentRead,
)
from documents.data.original_document.repository import OriginalDocumentRepository
from documents.data.document_batch.repository import DocumentBatchRepository
from documents.data.document_access.repository import DocumentAccessRepository
from documents.data.document_access_request.repository import DocumentAccessRequestRepository

__all__ = [
    "DocumentRepository",
    "CachedDocumentRepository",
    "DocumentRead",
    "OriginalDocumentRepository",
    "DocumentBatchRepository",
    "DocumentAccessRepository",
    "DocumentAccessRequestRepository",
]
