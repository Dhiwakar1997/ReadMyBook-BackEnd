-- Add reference_counter to original_documents (number of documents that refer to this og_doc).
-- When a document is deleted, the counter is decremented; when it reaches 0, og_doc chunks are removed from the vector DB.

ALTER TABLE original_documents
ADD COLUMN IF NOT EXISTS reference_counter INTEGER NOT NULL DEFAULT 0;

-- Backfill: set reference_counter = count of non-deleted documents that reference each og_doc
UPDATE original_documents od
SET reference_counter = COALESCE(
    (SELECT COUNT(*) FROM documents d
     WHERE d.original_document_id = od.original_document_id
       AND (d.is_deleted = FALSE OR d.is_deleted IS NULL)),
    0
);
