import os
from dotenv import load_dotenv

env_file = os.getenv("ENV_FILE", ".env.dev")
load_dotenv(env_file)

import json
import time
import base64
import subprocess
import datetime
import shutil
from typing import Any
from azure.storage.queue import QueueClient
from azure.storage.blob import BlobClient


from core.db_client import get_worker_db
from documents.data.model import Document, DocumentBatch, OriginalDocument
from users.data.model import User  # Import User so SQLAlchemy can resolve the foreign key
from documents.data.repository import DocumentRepository, DocumentBatchRepository, DocumentAccessRepository, OriginalDocumentRepository, CachedDocumentRepository
from shared.redis import RedisService

from worker.bolbHelper import download_pdf, upload_final_images, upload_md, upload_batch_pdf, upload_batch_markdown, download_batch_markdowns, list_images_in_container, copy_blobs, delete_blob_prefix
from worker.pdfBatchHelper import split_pdf_into_batches
from worker.filesHelper import delete_pdf_and_md, _merge_json_files, _merge_md_files, _ensure_clean_dir, _merge_meta_json
from worker.metadataHelper import create_md_metadata
from worker.vectorHelper import push_data_to_vector_db, delete_vectors_by_doc_id, update_vector_doc_ids
from worker.test_pdf_compare import get_file_hash
from billing.service.balance_service import BalanceService
import ulid


from urllib.parse import urlparse



QUEUE_NAME = os.getenv("QUEUE_NAME")
STORAGE_CONN = os.getenv("AZURE_CONNECTION_STRING")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "5"))

# Split the input PDF into page batches of this size (not related to marker's internal batching).
PDF_PAGES_PER_BATCH = int(os.getenv("PDF_PAGES_PER_BATCH", "10"))

# marker-pdf CLI tuning
MARKER_BATCH_SIZE = int(os.getenv("MARKER_BATCH_SIZE", "2"))
MARKER_DISABLE_OCR = os.getenv("MARKER_DISABLE_OCR", "true").strip().lower() in {"1", "true", "yes", "y"}

# Temporary processing directories
TMP_DIR = os.getenv("TMP_DIR", "tmp")
BATCHES_DIR = os.path.join(TMP_DIR, "batches")
FINAL_DIR = os.path.join(TMP_DIR, "final")
FINAL_IMAGES_DIR = os.path.join(FINAL_DIR, "images")
FINAL_MD_DIR = os.path.join(FINAL_DIR, "md")
FINAL_JSON_DIR = os.path.join(FINAL_DIR, "json")


if not STORAGE_CONN:
    raise RuntimeError("AZURE_CONNECTION_STRING is not set")
if not QUEUE_NAME:
    raise RuntimeError("QUEUE_NAME is not set")

STORAGE_CONN_STR: str = STORAGE_CONN
QUEUE_NAME_STR: str = QUEUE_NAME

queue = QueueClient.from_connection_string(conn_str=STORAGE_CONN_STR, queue_name=QUEUE_NAME_STR)


def _adjust_page_ids(obj, offset: int):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == "page_id" and isinstance(v, int):
                out[k] = v + offset
            else:
                out[k] = _adjust_page_ids(v, offset)
        return out
    if isinstance(obj, list):
        return [_adjust_page_ids(v, offset) for v in obj]
    return obj


def _rewrite_markdown_image_links(markdown_text: str, image_name_map: dict[str, str]) -> str:
    updated = markdown_text
    for old, new in image_name_map.items():
        updated = updated.replace(f"]({old})", f"]({new})")
        updated = updated.replace(f"](./{old})", f"](./{new})")
    return updated

def update_document(db, document, images: list[str], parse_time: datetime.timedelta):
    if document:
        print(f"Document found: {document.document_id}")
        document.status = "active"
        document.markdown_parse_time = round(parse_time.total_seconds(), 2)
        document.images = images
        document.updated_at = datetime.datetime.now()
        cached_doc_repo = CachedDocumentRepository(DocumentRepository(db), RedisService())
        cached_doc_repo.update_document(document)
        db.close()
        return True
    else:
        print(f"Document not found:     {document.document_id}")
        db.close()
        return False
    
def convert_to_md(input_pdf_path: str, *, output_root_dir: str) -> tuple[str, str, str]:
    """Convert a PDF to Markdown using marker_single.

    Returns:
        (output_md_path, output_json_path, output_folder)
    """
    base = os.path.splitext(os.path.basename(input_pdf_path))[0]
    output_folder = os.path.join(output_root_dir, base)
    output_md_path = os.path.join(output_folder, f"{base}.md")
    output_json_path = os.path.join(output_folder, f"{base}_meta.json")

    args = [
        "marker_single",
        input_pdf_path,
        "--output_dir",
        output_root_dir,
    ]
    if MARKER_DISABLE_OCR:
        args.append("--disable_ocr")

    print(f"Converting PDF to Markdown using marker_single: {os.path.basename(input_pdf_path)}")
    try:
        subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"Error converting PDF: {e.stderr}")
        raise
    except FileNotFoundError:
        print("marker_single command not found. Make sure marker-pdf is installed.")
        raise

    if not os.path.exists(output_md_path):
        raise FileNotFoundError(
            f"Generated markdown file not found at {output_md_path}. Conversion may have failed."
        )
    if not os.path.exists(output_json_path):
        raise FileNotFoundError(
            f"Generated metadata JSON file not found at {output_json_path}. Conversion may have failed."
        )

    return output_md_path, output_json_path, output_folder

def upload_md(blob_name: str, *, markdown_content: str, json_content: str) -> bool:
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


def process_batch_conversion(db, document_id: str, blob_name: str, container_name: str):
    """Process a single batch PDF: convert to markdown and update status."""
    print(f"[BATCH CONVERSION] Processing batch: {blob_name}")
    
    doc_repo = DocumentRepository(db)
    cached_doc_repo = CachedDocumentRepository(doc_repo, RedisService())
    batch_repo = DocumentBatchRepository(db)
    
    document = doc_repo.get_document_by_id(document_id)
    if not document:
        print(f"Document not found: {document_id}")
        return False
    
    batch_filename = os.path.basename(blob_name)
    batch_name = os.path.splitext(batch_filename)[0]
    
    try:
        batch_number = int(batch_name.split("_")[1])
    except (IndexError, ValueError):
        print(f"Invalid batch name format: {batch_name}")
        return False
    
    batch_record = batch_repo.get_document_batch(document_id, batch_number)
    if not batch_record:
        print(f"Batch record not found for document {document_id}, batch {batch_number}")
        return False
    
    try:
        input_pdf_path = download_pdf(container_name, blob_name)
        _ensure_clean_dir(BATCHES_DIR)
        
        start_time = datetime.datetime.now()
        
        output_md_path, output_json_path, output_folder = convert_to_md(
            input_pdf_path,
            output_root_dir=BATCHES_DIR,
        )
        
        with open(output_md_path, "r", encoding="utf-8") as f:
            batch_markdown = f.read()
        
        with open(output_json_path, "r", encoding="utf-8") as f:
            batch_meta = json.loads(f.read())
        
        image_files = [
            fn for fn in os.listdir(output_folder)
            if fn.lower().endswith((".jpeg", ".jpg"))
        ]
        image_name_map = {fn: f"{batch_name}_{fn}" for fn in image_files}
        if image_name_map:
            batch_markdown = _rewrite_markdown_image_links(batch_markdown, image_name_map)
        
        for original_name, staged_name in image_name_map.items():
            src = os.path.join(output_folder, original_name)
            temp_images_dir = os.path.join(BATCHES_DIR, "images")
            os.makedirs(temp_images_dir, exist_ok=True)
            dst = os.path.join(temp_images_dir, staged_name)
            shutil.copy2(src, dst)
        
        if image_name_map:
            uploaded_images = upload_final_images(os.path.join(BATCHES_DIR, "images"), document_id)
            if uploaded_images:
                print(f"Uploaded {len(uploaded_images)} images to storage (will update model during final merge)")
        
        page_offset = (batch_number - 1) * PDF_PAGES_PER_BATCH
        batch_meta = _adjust_page_ids(batch_meta, page_offset)
        
        upload_batch_markdown(
            document_id,
            batch_name,
            batch_markdown,
            json.dumps(batch_meta, ensure_ascii=False)
        )
        
        end_time = datetime.datetime.now()
        parse_time = end_time - start_time
        print(f"Batch {batch_name} conversion time: {parse_time.total_seconds():.2f} seconds")
        
        batch_repo.update_document_batch(document_id, batch_number, "completed", parse_time=round(parse_time.total_seconds(), 2))
        cached_doc_repo.increment_completed_batches(document_id)
        
        delete_pdf_and_md(input_pdf_path)
        
        if cached_doc_repo.is_all_batches_complete(document_id):
            print(f"All batches complete for document {document_id}, starting final merge...")
            process_final_merge(db, document_id)
        
        return True
        
    except Exception as e:
        print(f"Error processing batch {batch_name}: {e}")
        batch_repo.update_document_batch(document_id, batch_number, "failed")
        raise


def process_initial_batching(db, document_id: str, blob_name: str, container_name: str):
    """Split a PDF into batches and upload each batch for processing."""
    print(f"[INITIAL BATCHING] Processing document: {blob_name}")
    
    doc_repo = DocumentRepository(db)
    cached_doc_repo = CachedDocumentRepository(doc_repo, RedisService())
    batch_repo = DocumentBatchRepository(db)
    
    document = doc_repo.get_document_by_id(document_id)
    if not document:
        print(f"Document not found: {document_id}")
        return False
    
    try:
        cached_doc_repo.set_status(document_id, "processing")
        cached_doc_repo.update_final_job_status(document_id, "batching")

        input_pdf_path = download_pdf(container_name, blob_name)

        # --- PRE-PROCESSING HASH CHECK ---
        file_hash = get_file_hash(input_pdf_path)
        og_repo = OriginalDocumentRepository(db)
        existing_og = og_repo.get_by_hash(file_hash)

        if existing_og and existing_og.is_active:
            print(f"[DEDUP PRE-CHECK] Duplicate detected — og_doc={existing_og.original_document_id}")
            document.original_document_id = existing_og.original_document_id
            document.images = existing_og.images
            document.status = "active"
            cached_doc_repo.update_document(document)
            cached_doc_repo.update_final_job_status(document_id, "completed")
            DocumentAccessRepository(db).update_og_doc_id_for_document(document_id, existing_og.original_document_id)
            db.commit()
            delete_blob_prefix("pdfs", document_id)
            delete_pdf_and_md(input_pdf_path)
            print(f"[DEDUP PRE-CHECK] Skipped pipeline for {document_id}, linked to {existing_og.original_document_id}")
            return True

        _ensure_clean_dir(BATCHES_DIR)

        print(f"Splitting PDF into batches of {PDF_PAGES_PER_BATCH} page(s)")
        batch_pdf_paths, batch_offsets = split_pdf_into_batches(input_pdf_path, PDF_PAGES_PER_BATCH)
        total_batches = len(batch_pdf_paths)
        print(f"Created {total_batches} batch PDF(s)")
        
        cached_doc_repo.set_total_batches(document_id, total_batches)
        
        for i, batch_pdf_path in enumerate(batch_pdf_paths, start=1):
            batch_filename = os.path.basename(batch_pdf_path)
            blob_path = upload_batch_pdf(document_id, batch_filename, batch_pdf_path)
            
            batch_repo.create_document_batch(
                document_id=document_id,
                batch_number=i,
                status="pending",
                blob_path=blob_path
            )
            
            print(f"Batch {i}/{total_batches} uploaded and recorded: {blob_path}")
        
        cached_doc_repo.update_final_job_status(document_id, "processing")
        delete_pdf_and_md(input_pdf_path)
        
        print(f"Initial batching complete for document {document_id}: {total_batches} batches created")
        return True
        
    except Exception as e:
        print(f"Error during initial batching: {e}")
        cached_doc_repo.set_status(document_id, "failed")
        cached_doc_repo.update_final_job_status(document_id, "failed")
        raise


def process_final_merge(db, document_id: str):
    """Merge all batch markdowns into final document."""
    print(f"[FINAL MERGE] Merging batches for document: {document_id}")
    
    doc_repo = DocumentRepository(db)
    cached_doc_repo = CachedDocumentRepository(doc_repo, RedisService())
    
    document = doc_repo.get_document_by_id(document_id)
    if not document:
        print(f"Document not found: {document_id}")
        return False
    
    try:
        total_batches = document.total_batches or 0
        
        md_contents, json_contents = download_batch_markdowns(document_id, total_batches)
        merged_markdown = "\n\n".join(md_contents)
        
        meta_parts = [json.loads(jc) for jc in json_contents]
        merged_meta = _merge_meta_json(meta_parts)
        
        _ensure_clean_dir(FINAL_DIR)
        
        merged_md_path = os.path.join(FINAL_DIR, "merged.md")
        with open(merged_md_path, "w", encoding="utf-8") as f:
            f.write(merged_markdown)
        
        original_pdf_blob_name = f"{document_id}/{document_id}.pdf"
        input_pdf_path = download_pdf("pdfs", original_pdf_blob_name)
        
        print("Generating enhanced metadata...")
        metadata = create_md_metadata(merged_md_path, input_pdf_path, merged_meta)
        metadata_json = json.dumps(metadata, ensure_ascii=False)
        print(f"Metadata generated with {metadata.get('content_count', 0)} contents and {metadata.get('heading_count', 0)} headings")
        
        final_blob_name = f"{document_id}/{document_id}.pdf"
        upload_md(final_blob_name, markdown_content=merged_markdown, json_content=metadata_json)
        
        document.status = "active"
        document.updated_at = datetime.datetime.now()
        cached_doc_repo.update_document(document)
        cached_doc_repo.update_final_job_status(document_id, "completed")

        push_data_to_vector_db(metadata, document_id, document.owner_id, db=db)

        # ── Billing: deduct conversion cost based on total time ──────────────
        try:
            batch_repo = DocumentBatchRepository(db)
            total_seconds = batch_repo.get_total_parse_time(document_id)
            billing_svc = BalanceService()
            try:
                billing_svc.deduct_conversion_time_cost(
                    user_id=document.owner_id,
                    total_seconds=total_seconds,
                    document_id=document_id,
                )
                print(f"[billing] Deducted conversion cost for {total_seconds:.2f}s (user: {document.owner_id})")
            finally:
                billing_svc.close()
        except Exception as billing_exc:
            print(f"[billing] Conversion time deduction failed: {billing_exc}")

        print("Updating document images from blob storage...")
        image_filenames = list_images_in_container(document_id)
        if image_filenames:
            document.images = image_filenames
            cached_doc_repo.update_document(document)
            print(f"Updated document with {len(image_filenames)} images: {image_filenames}")
        else:
            print("No images found in blob storage for this document")

        # --- POST-PROCESSING HASH CHECK (dedup) ---
        file_hash = get_file_hash(input_pdf_path)
        og_repo = OriginalDocumentRepository(db)
        existing_og = og_repo.get_by_hash(file_hash)

        if existing_og:
            # DUPLICATE: another upload of the same file already created an og_doc
            print(f"[DEDUP POST-CHECK] Duplicate detected — linking to {existing_og.original_document_id}")
            document.original_document_id = existing_og.original_document_id
            document.images = existing_og.images
            cached_doc_repo.update_document(document)
            delete_vectors_by_doc_id(document_id)
            delete_blob_prefix("pdfs", document_id)
            delete_blob_prefix("markdowns", document_id)
            delete_blob_prefix("images", document_id)
        else:
            # NEW UNIQUE DOCUMENT: create og_doc record
            og_doc_id = "og_doc_" + str(ulid.new())
            og_doc = OriginalDocument(
                original_document_id=og_doc_id,
                file_hash=file_hash,
                size_in_kilobytes=document.size_in_kilobyes,
                images=image_filenames,
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

        DocumentAccessRepository(db).update_og_doc_id_for_document(document_id, document.original_document_id)
        db.commit()

        delete_pdf_and_md(input_pdf_path)

        print(f"Final merge complete for document {document_id}")
        return True
        
    except Exception as e:
        print(f"Error during final merge: {e}")
        cached_doc_repo.set_status(document_id, "failed")
        cached_doc_repo.update_final_job_status(document_id, "failed")
        raise


def process_message(event: dict):
    """Main message processor - routes to batch conversion or initial batching."""

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

        # Blobs copied to og_doc_* prefixes are archive copies — not new uploads.
        # Skip them to avoid reprocessing blobs that the dedup step created.
        if document_id.startswith("og_doc_"):
            print(f"Skipping og_doc blob (dedup archive copy): {container_name}/{blob_name}")
            return True

        db = next(get_worker_db())

        print(f"Processing blob: {container_name}/{blob_name}")

        if "/batches/" in blob_name:
            return process_batch_conversion(db, document_id, blob_name, container_name)
        else:
            return process_initial_batching(db, document_id, blob_name, container_name)

    except Exception as e:
        print("Error:", e)
        return False
    finally:
        if db is not None:
            db.close()

def main():
    print("Queue worker started")

    while True:
        messages = queue.receive_messages(messages_per_page=1, visibility_timeout=300)
        found = False
        for msg in messages:
            found = True
            
            if msg.dequeue_count >= 3:
                print(f"Message exceeded retry limit ({msg.dequeue_count} attempts), deleting...")
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