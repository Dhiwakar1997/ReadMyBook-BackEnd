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
from data.models.usersModel import User  # Import User so SQLAlchemy can resolve the foreign key

from worker.bolbHelper import download_pdf, upload_final_images,upload_md
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


def process_message(event: dict):

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
        
        print(container_name, blob_name)

        print(f"Processing blob: {container_name}/{blob_name}")

        # Download PDF
        input_pdf_path = download_pdf(container_name, blob_name)

        # Prepare final staging folders (must exist as batches complete)
        _ensure_clean_dir(FINAL_DIR)
        os.makedirs(FINAL_IMAGES_DIR, exist_ok=True)
        os.makedirs(FINAL_MD_DIR, exist_ok=True)
        os.makedirs(FINAL_JSON_DIR, exist_ok=True)

        # Clean batches folder for this run (holds batch PDFs + marker output folders)
        _ensure_clean_dir(BATCHES_DIR)

        # Split into batch PDFs and convert each batch sequentially
        print(f"Splitting PDF into batches of {PDF_PAGES_PER_BATCH} page(s)")
        batch_pdf_paths, batch_offsets = split_pdf_into_batches(input_pdf_path, PDF_PAGES_PER_BATCH)
        print(f"Created {len(batch_pdf_paths)} batch PDF(s)")

        start_time = datetime.datetime.now()

        for i, (batch_pdf_path, page_offset) in enumerate(zip(batch_pdf_paths, batch_offsets), start=1):
            batch_name = os.path.splitext(os.path.basename(batch_pdf_path))[0]
            print(f"Processing {batch_name} (page_id offset {page_offset})")

            output_md_path, output_json_path, output_folder = convert_to_md(
                batch_pdf_path,
                output_root_dir=BATCHES_DIR,
            )

            with open(output_md_path, "r", encoding="utf-8") as f:
                batch_markdown = f.read()

            with open(output_json_path, "r", encoding="utf-8") as f:
                batch_meta = json.loads(f.read())

            # Make image names unique across batches to avoid blob overwrites.
            image_files = [
                fn
                for fn in os.listdir(output_folder)
                if fn.lower().endswith((".jpeg", ".jpg"))
            ]
            image_name_map = {fn: f"{batch_name}_{fn}" for fn in image_files}
            if image_name_map:
                batch_markdown = _rewrite_markdown_image_links(batch_markdown, image_name_map)

            # Stage images into final/images (do not upload until all batches complete)
            for original_name, staged_name in image_name_map.items():
                src = os.path.join(output_folder, original_name)
                dst = os.path.join(FINAL_IMAGES_DIR, staged_name)
                shutil.copy2(src, dst)

            # Stage markdown into final/md
            staged_md_path = os.path.join(FINAL_MD_DIR, f"{batch_name}.md")
            with open(staged_md_path, "w", encoding="utf-8") as f:
                f.write(batch_markdown)

            # Adjust page_id fields so merged JSON has consistent global indexing.
            batch_meta = _adjust_page_ids(batch_meta, page_offset)

            # Stage adjusted json into final/json
            staged_json_path = os.path.join(FINAL_JSON_DIR, f"{batch_name}_meta.json")
            with open(staged_json_path, "w", encoding="utf-8") as f:
                f.write(json.dumps(batch_meta, ensure_ascii=False))

        end_time = datetime.datetime.now()
        parse_time = end_time - start_time
        print(f"Total Markdown conversion time: {parse_time.total_seconds():.2f} seconds")

        # Upload all staged images (only after all batches are done)
        uploaded_image_names = upload_final_images(FINAL_IMAGES_DIR, document_id)

        # Merge MD files into a single MD (using disk to avoid huge memory spikes)
        merged_md_path = os.path.join(FINAL_DIR, "merged.md")
        _merge_md_files(FINAL_MD_DIR, merged_md_path)
        with open(merged_md_path, "r", encoding="utf-8") as f:
            merged_markdown = f.read()

        # Merge JSON files into a single JSON
        merged_meta = _merge_json_files(FINAL_JSON_DIR)
        
        # Generate enhanced metadata from the merged markdown and PDF
        print("Generating enhanced metadata...")
        metadata = create_md_metadata(merged_md_path, input_pdf_path, merged_meta)
        metadata_json = json.dumps(metadata, ensure_ascii=False)
        print(f"Metadata generated with {metadata['content_count']} contents and {metadata['heading_count']} headings")

        # Upload merged Markdown + enhanced metadata JSON
        upload_md(blob_name, markdown_content=merged_markdown, json_content=metadata_json)
        
        db = next(get_db())
        document: Any = db.query(Document).filter(Document.document_id == document_id).first()

        push_data_to_vector_db(metadata, document_id, document.owner_id)
        
        update_document(db, document, uploaded_image_names, parse_time)
        
        # Clean up temporary files
        delete_pdf_and_md(input_pdf_path)
        
        return True
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