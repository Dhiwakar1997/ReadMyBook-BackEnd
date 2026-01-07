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
from pypdf import PdfReader, PdfWriter

from data.dbClient import get_db
from data.models.documentsModel import Document
from data.models.documentBatchModel import DocumentBatch
from data.models.usersModel import User  # Import User so SQLAlchemy can resolve the foreign key
from data.repositories.documentRepository import DocumentRepository
from data.repositories.documentBatchRepository import DocumentBatchRepository

from worker.bolbHelper import download_pdf, upload_final_images, upload_md, upload_batch_pdf, upload_batch_markdown, download_batch_markdowns
from worker.pdfBatchHelper import split_pdf_into_batches
from worker.filesHelper import delete_pdf_and_md, _merge_json_files, _merge_md_files, _ensure_clean_dir, _merge_meta_json
from worker.metadataHelper import create_md_metadata
from worker.vectorHelper import push_data_to_vector_db


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

def update_document(db,document, images: list[str], parse_time: datetime.timedelta):

    if document:
        print(f"Document found: {document.document_id}")
        document.is_active = True
        document.markdown_parse_time = round(parse_time.total_seconds(), 2)
        document.images = images
        document.updated_at = datetime.datetime.now()
        db.commit()
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
    output_blob_name = os.path.splitext(blob_name)[0] + ".md"
    output_blob = BlobClient.from_connection_string(
        conn_str=STORAGE_CONN_STR,
        container_name="markdown",
        blob_name=output_blob_name,
    )
    output_blob.upload_blob(markdown_content, overwrite=True)

    output_json_blob_name = os.path.splitext(blob_name)[0] + ".json"
    output_json_blob = BlobClient.from_connection_string(
        conn_str=STORAGE_CONN_STR,
        container_name="markdown",
        blob_name=output_json_blob_name,
    )
    output_json_blob.upload_blob(json_content, overwrite=True)

    print("Markdown and json uploaded:", output_blob_name)
    return True


def process_batch_conversion(db, document_id: str, blob_name: str, container_name: str):
    """Process a single batch PDF: convert to markdown and update status.
    
    This is called when a batch PDF is uploaded to {doc_id}/batches/{batch}.pdf
    """
    print(f"[BATCH CONVERSION] Processing batch: {blob_name}")
    
    doc_repo = DocumentRepository(db)
    batch_repo = DocumentBatchRepository(db)
    
    # Get the document and batch info
    document = doc_repo.get_document_by_id(document_id)
    if not document:
        print(f"Document not found: {document_id}")
        return False
    
    # Extract batch name from blob path (e.g., "doc_id/batches/batch_0001.pdf" -> "batch_0001")
    batch_filename = os.path.basename(blob_name)
    batch_name = os.path.splitext(batch_filename)[0]
    
    # Extract batch number from batch name (e.g., "batch_0001" -> 1)
    try:
        batch_number = int(batch_name.split("_")[1])
    except (IndexError, ValueError):
        print(f"Invalid batch name format: {batch_name}")
        return False
    
    # Look up batch record by blob_path
    batch_record = batch_repo.get_document_batch(document_id, batch_number)
    if not batch_record:
        print(f"Batch record not found for document {document_id}, batch {batch_number}")
        return False
    
    try:
        # Download the batch PDF
        input_pdf_path = download_pdf(container_name, blob_name)
        
        # Prepare output directories
        _ensure_clean_dir(BATCHES_DIR)
        
        start_time = datetime.datetime.now()
        
        # Convert to markdown
        output_md_path, output_json_path, output_folder = convert_to_md(
            input_pdf_path,
            output_root_dir=BATCHES_DIR,
        )
        
        # Read the generated content
        with open(output_md_path, "r", encoding="utf-8") as f:
            batch_markdown = f.read()
        
        with open(output_json_path, "r", encoding="utf-8") as f:
            batch_meta = json.loads(f.read())
        
        # Handle images - make names unique with batch prefix
        image_files = [
            fn for fn in os.listdir(output_folder)
            if fn.lower().endswith((".jpeg", ".jpg"))
        ]
        image_name_map = {fn: f"{batch_name}_{fn}" for fn in image_files}
        if image_name_map:
            batch_markdown = _rewrite_markdown_image_links(batch_markdown, image_name_map)
        
        # Upload images to image container
        for original_name, staged_name in image_name_map.items():
            src = os.path.join(output_folder, original_name)
            # Copy to a temp location with new name and upload
            temp_images_dir = os.path.join(BATCHES_DIR, "images")
            os.makedirs(temp_images_dir, exist_ok=True)
            dst = os.path.join(temp_images_dir, staged_name)
            shutil.copy2(src, dst)
        
        if image_name_map:
            upload_final_images(os.path.join(BATCHES_DIR, "images"), document_id)
        
        # Calculate page offset based on batch number and pages per batch
        page_offset = (batch_number - 1) * PDF_PAGES_PER_BATCH
        batch_meta = _adjust_page_ids(batch_meta, page_offset)
        
        # Upload batch markdown and JSON to markdown container
        upload_batch_markdown(
            document_id,
            batch_name,
            batch_markdown,
            json.dumps(batch_meta, ensure_ascii=False)
        )
        
        end_time = datetime.datetime.now()
        parse_time = end_time - start_time
        print(f"Batch {batch_name} conversion time: {parse_time.total_seconds():.2f} seconds")
        
        # Update batch status to completed
        batch_repo.update_document_batch(document_id, batch_number, "completed")
        
        # Increment completed_batches on document
        doc_repo.increment_completed_batches(document_id)
        
        # Clean up
        delete_pdf_and_md(input_pdf_path)
        
        # Check if all batches are complete
        if doc_repo.is_all_batches_complete(document_id):
            print(f"All batches complete for document {document_id}, starting final merge...")
            process_final_merge(db, document_id)
        
        return True
        
    except Exception as e:
        print(f"Error processing batch {batch_name}: {e}")
        batch_repo.update_document_batch(document_id, batch_number, "failed")
        raise


def process_initial_batching(db, document_id: str, blob_name: str, container_name: str):
    """Split a PDF into batches and upload each batch for processing.
    
    This is called when a full PDF is uploaded (not in batches path).
    """
    print(f"[INITIAL BATCHING] Processing document: {blob_name}")
    
    doc_repo = DocumentRepository(db)
    batch_repo = DocumentBatchRepository(db)
    
    document = doc_repo.get_document_by_id(document_id)
    if not document:
        print(f"Document not found: {document_id}")
        return False
    
    try:
        # Update job status to processing
        doc_repo.update_final_job_status(document_id, "batching")
        
        # Download the full PDF
        input_pdf_path = download_pdf(container_name, blob_name)
        
        # Prepare directories
        _ensure_clean_dir(BATCHES_DIR)
        
        # Split into batch PDFs
        print(f"Splitting PDF into batches of {PDF_PAGES_PER_BATCH} page(s)")
        batch_pdf_paths, batch_offsets = split_pdf_into_batches(input_pdf_path, PDF_PAGES_PER_BATCH)
        total_batches = len(batch_pdf_paths)
        print(f"Created {total_batches} batch PDF(s)")
        
        # Update document with total batch count
        doc_repo.set_total_batches(document_id, total_batches)
        
        # Upload each batch and create DB records
        for i, batch_pdf_path in enumerate(batch_pdf_paths, start=1):
            batch_filename = os.path.basename(batch_pdf_path)
            
            # Upload batch PDF to blob storage
            blob_path = upload_batch_pdf(document_id, batch_filename, batch_pdf_path)
            
            # Create batch record in database
            batch_repo.create_document_batch(
                document_id=document_id,
                batch_number=i,
                status="pending",
                blob_path=blob_path
            )
            
            print(f"Batch {i}/{total_batches} uploaded and recorded: {blob_path}")
        
        # Update job status
        doc_repo.update_final_job_status(document_id, "processing")
        
        # Clean up local files
        delete_pdf_and_md(input_pdf_path)
        
        print(f"Initial batching complete for document {document_id}: {total_batches} batches created")
        return True
        
    except Exception as e:
        print(f"Error during initial batching: {e}")
        doc_repo.update_final_job_status(document_id, "failed")
        raise


def process_final_merge(db, document_id: str):
    """Merge all batch markdowns into final document.
    
    Called automatically when all batches are complete.
    """
    print(f"[FINAL MERGE] Merging batches for document: {document_id}")
    
    doc_repo = DocumentRepository(db)
    
    document = doc_repo.get_document_by_id(document_id)
    if not document:
        print(f"Document not found: {document_id}")
        return False
    
    try:
        total_batches = document.total_batches or 0
        
        # Download all batch markdowns from blob storage
        md_contents, json_contents = download_batch_markdowns(document_id, total_batches)
        
        # Merge markdown content
        merged_markdown = "\n\n".join(md_contents)
        
        # Merge JSON metadata
        meta_parts = [json.loads(jc) for jc in json_contents]
        merged_meta = _merge_meta_json(meta_parts)
        
        # Prepare temp directory for merged files
        _ensure_clean_dir(FINAL_DIR)
        
        # Save merged markdown to temp file (needed for create_md_metadata)
        merged_md_path = os.path.join(FINAL_DIR, "merged.md")
        with open(merged_md_path, "w", encoding="utf-8") as f:
            f.write(merged_markdown)
        
        # Download original PDF from blob storage for metadata extraction
        original_pdf_blob_name = f"{document_id}/{document_id}.pdf"
        input_pdf_path = download_pdf("pdf", original_pdf_blob_name)
        
        # Generate enhanced metadata from the merged markdown and PDF
        print("Generating enhanced metadata...")
        metadata = create_md_metadata(merged_md_path, input_pdf_path, merged_meta)
        metadata_json = json.dumps(metadata, ensure_ascii=False)
        print(f"Metadata generated with {metadata.get('content_count', 0)} contents and {metadata.get('heading_count', 0)} headings")
        
        # Upload final merged files
        final_blob_name = f"{document_id}/{document_id}.pdf"  # Use document path format
        upload_md(final_blob_name, markdown_content=merged_markdown, json_content=metadata_json)
        
        # Update document status
        document.is_active = True
        document.updated_at = datetime.datetime.now()
        doc_repo.update_final_job_status(document_id, "completed")
        db.commit()

        #
        push_data_to_vector_db(metadata, document_id,document.owner_id)
        
        # Clean up temp files
        delete_pdf_and_md(input_pdf_path)
        
        print(f"Final merge complete for document {document_id}")
        return True
        
    except Exception as e:
        print(f"Error during final merge: {e}")
        doc_repo.update_final_job_status(document_id, "failed")
        raise


def process_message(event: dict):
    """Main message processor - routes to batch conversion or initial batching."""

    try:
        if event.get("eventType") != "Microsoft.Storage.BlobCreated":
            print("Skipping non-BlobCreated event")
            return False

        blob_url = event["data"]["url"]

        # Parse container & blob
        parsed = urlparse(blob_url)
        path_parts = parsed.path.lstrip("/").split("/", 1)

        container_name = path_parts[0]
        blob_name = path_parts[1]

        document_id = blob_name.split("/")[0]

        db = next(get_db())

        print(f"Processing blob: {container_name}/{blob_name}")

        # Route based on whether this is a batch PDF or initial upload
        if "/batches/" in blob_name:
            # This is a batch PDF - convert to markdown
            return process_batch_conversion(db, document_id, blob_name, container_name)
        else:
            # This is the initial PDF - split into batches
            return process_initial_batching(db, document_id, blob_name, container_name)

    except Exception as e:
        print("Error:", e)
        return False

def main():
    print("Queue worker started")

    while True:
        messages = queue.receive_messages(messages_per_page=1, visibility_timeout=300)
        found = False
        for msg in messages:
            found = True
            try:
                raw = base64.b64decode(msg.content).decode("utf-8")
                payload = json.loads(raw)

                processed = process_message(payload)
                if processed:
                    print("Message processed successfully")
                    #queue.update_message(msg, visibility_timeout=60)
                    queue.delete_message(msg)
                else:
                    print("Message not processed")
                    queue.update_message(msg, visibility_timeout=300)

            except Exception as e:
                print("Error:", e)
                queue.update_message(msg, visibility_timeout=300)

        if not found:
            time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()