"""
worker_v2 — PDF processing worker using PyMuPDF.

Replaces marker-pdf with a lightweight PyMuPDF-based converter.
No batching needed: entire PDFs are processed in a single pass (~2-3s
for a 600-page book vs minutes with marker-pdf).

All existing features are preserved: dedup, enrichment (chapters,
summary, category), and vector DB push.
"""

import os
from dotenv import load_dotenv

env_file = os.getenv("ENV_FILE", ".env.dev")
load_dotenv(env_file)

import json
import time
import base64
import datetime
import shutil
from typing import Any
from urllib.parse import urlparse
from azure.storage.queue import QueueClient
from azure.storage.blob import BlobClient

from core.db_client import get_worker_db
from documents.data.model import Document, DocumentBatch, OriginalDocument
from users.data.model import User
from documents.data.repository import (
    DocumentRepository,
    DocumentBatchRepository,
    DocumentAccessRepository,
    OriginalDocumentRepository,
    CachedDocumentRepository,
)
from shared.redis import RedisService

from worker.bolbHelper import (
    download_pdf,
    upload_final_images,
    upload_md as blob_upload_md,
    list_images_in_container,
    copy_blobs,
    delete_blob_prefix,
)
from worker.filesHelper import delete_pdf_and_md, _ensure_clean_dir
from worker.metadataHelper import create_md_metadata, detect_chapters
from worker.vectorHelper import push_data_to_vector_db, delete_vectors_by_doc_id, update_vector_doc_ids
from worker.enrichmentHelper import generate_book_summary, classify_book_category, classify_sub_categories
from worker.test_pdf_compare import get_file_hash
import ulid

from worker_v2.converter import convert_pdf_to_markdown
from worker_v2.image_extractor import extract_images_with_positions
from worker_v2.md_image_inserter import insert_images_into_markdown


QUEUE_NAME = os.getenv("QUEUE_NAME")
STORAGE_CONN = os.getenv("AZURE_CONNECTION_STRING")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "5"))

TMP_DIR = os.getenv("TMP_DIR", "tmp")
IMAGES_DIR = os.path.join(TMP_DIR, "images")

if not STORAGE_CONN:
    raise RuntimeError("AZURE_CONNECTION_STRING is not set")
if not QUEUE_NAME:
    raise RuntimeError("QUEUE_NAME is not set")

STORAGE_CONN_STR: str = STORAGE_CONN
QUEUE_NAME_STR: str = QUEUE_NAME

queue = QueueClient.from_connection_string(conn_str=STORAGE_CONN_STR, queue_name=QUEUE_NAME_STR)


def upload_md(blob_name: str, *, markdown_content: str, json_content: str) -> bool:
    """Upload markdown and JSON metadata to the markdowns blob container."""
    print(f"Uploading markdown and json to blob storage: {blob_name}")
    output_blob_name = os.path.splitext(blob_name)[0] + ".md"
    output_blob = BlobClient.from_connection_string(
        conn_str=STORAGE_CONN_STR,
        container_name="markdowns",
        blob_name=output_blob_name,
    )
    output_blob.upload_blob(markdown_content, overwrite=True)

    output_json_blob_name = os.path.splitext(blob_name)[0] + ".json"
    output_json_blob = BlobClient.from_connection_string(
        conn_str=STORAGE_CONN_STR,
        container_name="markdowns",
        blob_name=output_json_blob_name,
    )
    output_json_blob.upload_blob(json_content, overwrite=True)

    print("Markdown and json uploaded:", output_blob_name)
    return True


def process_document(db, document_id: str, blob_name: str, container_name: str):
    """Full pipeline: PDF -> Markdown -> images -> metadata -> enrichment -> vector DB."""
    print(f"[PROCESS] Processing document: {blob_name}")

    doc_repo = DocumentRepository(db)
    cached_doc_repo = CachedDocumentRepository(doc_repo, RedisService())

    document = doc_repo.get_document_by_id(document_id)
    if not document:
        print(f"Document not found: {document_id}")
        return False

    try:
        cached_doc_repo.set_status(document_id, "processing")
        cached_doc_repo.update_final_job_status(document_id, "processing")

        input_pdf_path = download_pdf(container_name, blob_name)
        start_time = datetime.datetime.now()

        # ── Pre-dedup hash check ─────────────────────────────────────────
        file_hash = get_file_hash(input_pdf_path)
        og_repo = OriginalDocumentRepository(db)
        existing_og = og_repo.get_by_hash(file_hash)

        if existing_og and existing_og.is_active:
            print(f"[DEDUP PRE-CHECK] Duplicate detected — og_doc={existing_og.original_document_id}")
            document.original_document_id = existing_og.original_document_id
            document.images = existing_og.images
            document.generated_title = existing_og.generated_title
            document.display_name = existing_og.generated_title or document.display_name
            document.category = existing_og.category
            document.sub_categories = existing_og.sub_categories
            og_repo.increment_reference_counter(existing_og.original_document_id)
            DocumentAccessRepository(db).update_og_doc_id_for_document(
                document_id, existing_og.original_document_id
            )
            db.commit()
            delete_blob_prefix("pdfs", document_id)
            delete_pdf_and_md(input_pdf_path)
            document.status = "active"
            cached_doc_repo.update_document(document)
            cached_doc_repo.update_final_job_status(document_id, "completed")
            print(f"[DEDUP PRE-CHECK] Skipped pipeline for {document_id}, linked to {existing_og.original_document_id}")
            return True

        # ── Step 1: PDF -> Markdown (PyMuPDF) ────────────────────────────
        print("Step 1: Converting PDF to Markdown (PyMuPDF)...")
        md_text = convert_pdf_to_markdown(input_pdf_path)
        print(f"  Markdown: {len(md_text):,} chars, {md_text.count(chr(10)):,} lines")

        # ── Step 2: Extract images with positional context ───────────────
        print("Step 2: Extracting images with positional context...")
        _ensure_clean_dir(IMAGES_DIR)
        image_results = extract_images_with_positions(input_pdf_path, IMAGES_DIR)
        saved_images = [r for r in image_results if r.get("image_saved")]
        print(f"  Extracted {len(saved_images)} images")

        # ── Step 3: Insert image tags into Markdown ──────────────────────
        print("Step 3: Inserting image tags into Markdown...")
        md_with_images = insert_images_into_markdown(
            md_text, image_results, images_rel_dir=f"{document_id}"
        )

        # ── Step 4: Upload images to blob storage ────────────────────────
        print("Step 4: Uploading images to blob storage...")
        if saved_images:
            uploaded_images = upload_final_images(IMAGES_DIR, document_id)
            print(f"  Uploaded {len(uploaded_images)} images")

        # ── Step 5: Write temp Markdown and create metadata ──────────────
        print("Step 5: Creating metadata...")
        os.makedirs(TMP_DIR, exist_ok=True)
        merged_md_path = os.path.join(TMP_DIR, "merged.md")
        with open(merged_md_path, "w", encoding="utf-8") as f:
            f.write(md_with_images)

        metadata = create_md_metadata(merged_md_path, input_pdf_path, {"table_of_contents": []})
        print(f"  Metadata: {metadata.get('content_count', 0)} contents, "
              f"{metadata.get('heading_count', 0)} headings")

        # ── Step 6: Enrichment ───────────────────────────────────────────
        print("Step 6a: Running chapter detection...")
        metadata, _ = detect_chapters(metadata)

        print("Step 6b: Running book enrichment (summary + categorization)...")
        summary_result, _ = generate_book_summary(metadata)
        enrichment_category, _ = classify_book_category(metadata)
        enrichment_sub_categories, _ = classify_sub_categories(metadata, enrichment_category)

        metadata["title"] = summary_result["title"]
        metadata["summary"] = summary_result["summary"]
        metadata["category"] = enrichment_category
        metadata["sub_categories"] = enrichment_sub_categories

        metadata_json = json.dumps(metadata, ensure_ascii=False)

        # ── Step 7: Upload Markdown + metadata ───────────────────────────
        print("Step 7: Uploading Markdown + metadata to blob storage...")
        final_blob_name = f"{document_id}/{document_id}.pdf"
        upload_md(final_blob_name, markdown_content=md_with_images, json_content=metadata_json)

        # ── Update document record ───────────────────────────────────────
        document.generated_title = summary_result["title"]
        document.display_name = summary_result["title"]
        document.category = enrichment_category
        document.sub_categories = enrichment_sub_categories

        end_time = datetime.datetime.now()
        parse_time = end_time - start_time
        document.markdown_parse_time = round(parse_time.total_seconds(), 2)

        cached_doc_repo.update_document(document)

        # ── Step 8: Vector DB push ───────────────────────────────────────
        print("Step 8: Pushing to vector DB...")
        push_data_to_vector_db(metadata, document_id, document.owner_id, db=db)

        # ── Step 9: Update images from blob storage ──────────────────────
        print("Updating document images from blob storage...")
        image_filenames = list_images_in_container(document_id)
        if image_filenames:
            document.images = image_filenames
            cached_doc_repo.update_document(document)
            print(f"Updated document with {len(image_filenames)} images")
        else:
            print("No images found in blob storage for this document")

        # ── Step 10: Post-dedup ──────────────────────────────────────────
        existing_og = og_repo.get_by_hash(file_hash)

        if existing_og:
            print(f"[DEDUP POST-CHECK] Duplicate detected — linking to {existing_og.original_document_id}")
            document.original_document_id = existing_og.original_document_id
            document.images = existing_og.images
            document.generated_title = existing_og.generated_title
            document.display_name = existing_og.generated_title or document.display_name
            document.category = existing_og.category
            document.sub_categories = existing_og.sub_categories
            cached_doc_repo.update_document(document)
            og_repo.increment_reference_counter(existing_og.original_document_id)
            delete_vectors_by_doc_id(document_id)
            delete_blob_prefix("pdfs", document_id)
            delete_blob_prefix("markdowns", document_id)
            delete_blob_prefix("images", document_id)
        else:
            og_doc_id = "og_doc_" + str(ulid.new())
            og_doc = OriginalDocument(
                original_document_id=og_doc_id,
                file_hash=file_hash,
                size_in_kilobytes=document.size_in_kilobyes,
                reference_counter=1,
                images=image_filenames,
                generated_title=summary_result["title"],
                summary=summary_result["summary"],
                category=enrichment_category,
                sub_categories=enrichment_sub_categories,
            )
            og_repo.create(og_doc)
            document.original_document_id = og_doc_id
            cached_doc_repo.update_document(document)
            print(f"[DEDUP POST-CHECK] New og_doc created: {og_doc_id}")

            copy_blobs("pdfs", document_id, og_doc_id)
            copy_blobs("markdowns", document_id, og_doc_id)
            copy_blobs("images", document_id, og_doc_id)
            delete_blob_prefix("pdfs", document_id)
            delete_blob_prefix("markdowns", document_id)
            delete_blob_prefix("images", document_id)
            update_vector_doc_ids(document_id, og_doc_id)

        DocumentAccessRepository(db).update_og_doc_id_for_document(
            document_id, document.original_document_id
        )
        db.commit()

        # ── Cleanup ──────────────────────────────────────────────────────
        delete_pdf_and_md(input_pdf_path)
        document.status = "active"
        document.updated_at = datetime.datetime.now()
        cached_doc_repo.update_document(document)
        cached_doc_repo.update_final_job_status(document_id, "completed")

        total_elapsed = (datetime.datetime.now() - start_time).total_seconds()
        print(f"[PROCESS] Document {document_id} complete in {total_elapsed:.2f}s")
        return True

    except Exception as e:
        print(f"Error processing document: {e}")
        cached_doc_repo.set_status(document_id, "failed")
        cached_doc_repo.update_final_job_status(document_id, "failed")
        raise


def _mark_document_failed_after_retry_limit(payload: dict) -> None:
    """Mark document as failed after retry exhaustion."""
    try:
        if payload.get("eventType") != "Microsoft.Storage.BlobCreated":
            return

        blob_url = payload["data"]["url"]
        parsed = urlparse(blob_url)
        path_parts = parsed.path.lstrip("/").split("/", 1)
        if len(path_parts) < 2:
            return

        blob_name = path_parts[1]
        document_id = blob_name.split("/")[0]

        if document_id.startswith("og_doc_"):
            return

        db = next(get_worker_db())
        try:
            doc_repo = DocumentRepository(db)
            cached_doc_repo = CachedDocumentRepository(doc_repo, RedisService())
            cached_doc_repo.set_status(document_id, "failed")
            cached_doc_repo.update_final_job_status(document_id, "failed")
            db.commit()
            print(f"[RETRY-LIMIT] Marked document {document_id} as failed after 3 retries")
        finally:
            db.close()
    except Exception as e:
        print(f"[RETRY-LIMIT] Error marking failed after retry limit: {e}")


def process_message(event: dict):
    """Main message processor — routes blob events to document processing."""
    db = None
    try:
        if event.get("eventType") != "Microsoft.Storage.BlobCreated":
            print("Skipping non-BlobCreated event")
            return False

        blob_url = event["data"]["url"]
        parsed = urlparse(blob_url)
        path_parts = parsed.path.lstrip("/").split("/", 1)

        container_name = path_parts[0]
        blob_name = path_parts[1]
        document_id = blob_name.split("/")[0]

        if document_id.startswith("og_doc_"):
            print(f"Skipping og_doc blob (dedup archive copy): {container_name}/{blob_name}")
            return True

        if "/batches/" in blob_name:
            print(f"Skipping batch blob (not used by worker_v2): {container_name}/{blob_name}")
            return True

        db = next(get_worker_db())
        print(f"Processing blob: {container_name}/{blob_name}")
        return process_document(db, document_id, blob_name, container_name)

    except Exception as e:
        print("Error:", e)
        return False
    finally:
        if db is not None:
            db.close()


def main():
    print("Queue worker v2 started (PyMuPDF pipeline)")

    while True:
        messages = queue.receive_messages(messages_per_page=1, visibility_timeout=300)
        found = False
        for msg in messages:
            found = True

            if msg.dequeue_count >= 3:
                print(f"Message exceeded retry limit ({msg.dequeue_count} attempts), "
                      "marking document failed...")
                try:
                    raw = base64.b64decode(msg.content).decode("utf-8")
                    payload = json.loads(raw)
                    _mark_document_failed_after_retry_limit(payload)
                except Exception as e:
                    print(f"Error handling 3x-failed message: {e}")
                queue.delete_message(msg)
                continue

            try:
                raw = base64.b64decode(msg.content).decode("utf-8")
                payload = json.loads(raw)

                processed = process_message(payload)
                if processed:
                    print("Message processed successfully")
                    queue.delete_message(msg)
                else:
                    print(f"Message not processed (attempt {msg.dequeue_count}/3)")
                    queue.update_message(msg, visibility_timeout=300)

            except Exception as e:
                print(f"Error (attempt {msg.dequeue_count}/3):", e)
                queue.update_message(msg, visibility_timeout=300)

        if not found:
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
