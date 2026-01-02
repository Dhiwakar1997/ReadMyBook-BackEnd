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

def split_pdf_into_batches(input_pdf_path: str, pages_per_batch: int) -> tuple[list[str], list[int]]:
    """Split a PDF into multiple batch PDFs.

    Returns:
        (batch_pdf_paths, batch_page_offsets)
        - batch_pdf_paths: list of generated batch PDF paths
        - batch_page_offsets: for each batch, the 0-based page_id offset to apply
    """
    if pages_per_batch <= 0:
        raise ValueError("PDF_PAGES_PER_BATCH must be > 0")

    os.makedirs(BATCHES_DIR, exist_ok=True)

    print(f"[split_pdf_into_batches] input_pdf_path={input_pdf_path}")
    print(f"[split_pdf_into_batches] pages_per_batch={pages_per_batch}")

    batch_pdf_paths: list[str] = []
    batch_offsets: list[int] = []

    # Keep the PDF file open for the entire batching process
    with open(input_pdf_path, "rb") as pdf_file:
        reader = PdfReader(pdf_file)
        total_pages = len(reader.pages)

        if total_pages == 0:
            print("[split_pdf_into_batches] WARNING: PDF has 0 pages")
            return batch_pdf_paths, batch_offsets

        total_batches = (total_pages + pages_per_batch - 1) // pages_per_batch
        print(f"[split_pdf_into_batches] total_pages={total_pages}, total_batches={total_batches}")

        page_index = 0
        batch_index = 0
        while page_index < total_pages:
            batch_index += 1
            start0 = page_index
            end0_exclusive = min(page_index + pages_per_batch, total_pages)

            batch_name = f"batch_{batch_index:04d}"
            batch_pdf_path = os.path.join(BATCHES_DIR, f"{batch_name}.pdf")

            # Human friendly: 1-based page range
            print(
                f"[split_pdf_into_batches] creating {batch_name}: pages {start0 + 1}-{end0_exclusive} -> {batch_pdf_path}"
            )

            writer = PdfWriter()
            for p in range(start0, end0_exclusive):
                writer.add_page(reader.pages[p])

            with open(batch_pdf_path, "wb") as out_f:
                writer.write(out_f)

            try:
                size_mb = os.path.getsize(batch_pdf_path) / (1024 * 1024)
                print(f"[split_pdf_into_batches] wrote {batch_name} ({size_mb:.2f} MB)")
            except OSError:
                pass

            batch_pdf_paths.append(batch_pdf_path)
            batch_offsets.append(start0)  # 0-based offset for meta page_id

            page_index = end0_exclusive

    return batch_pdf_paths, batch_offsets

def download_pdf(container_name: str, blob_name: str) -> str:

    blob_client = BlobClient.from_connection_string(
        conn_str=STORAGE_CONN_STR,
        container_name=container_name,
        blob_name=blob_name
    )
    
    pdf_bytes = blob_client.download_blob().readall()
    os.makedirs(TMP_DIR, exist_ok=True)
    input_pdf_path = os.path.join(TMP_DIR, "input.pdf")
    
    with open(input_pdf_path, "wb") as f:
        f.write(pdf_bytes)
    print(f"PDF downloaded successfully to {input_pdf_path}")
    
    return input_pdf_path

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


def upload_final_images(images_folder: str, document_id: str) -> list[str]:
    """Upload all images in a folder to the image container under document_id/.

    Returns:
        list of uploaded image filenames (not full blob paths)
    """
    if not os.path.exists(images_folder):
        print(f"Final images folder not found: {images_folder}")
        return []

    image_files = sorted(
        [f for f in os.listdir(images_folder) if f.lower().endswith((".jpeg", ".jpg"))]
    )
    if not image_files:
        print(f"No images found in final images folder: {images_folder}")
        return []

    uploaded_names: list[str] = []
    print(f"Uploading {len(image_files)} image(s) from final folder")
    for filename in image_files:
        local_path = os.path.join(images_folder, filename)
        blob_name = document_id + "/" + filename
        try:
            image_blob = BlobClient.from_connection_string(
                conn_str=STORAGE_CONN_STR,
                container_name="image",
                blob_name=blob_name,
            )
            with open(local_path, "rb") as f:
                image_blob.upload_blob(f, overwrite=True)
            uploaded_names.append(filename)
        except Exception as e:
            print(f"Error uploading image {filename}: {e}")
            raise

    return uploaded_names

def upload_images(input_folder: str, document_id: str, *, image_name_map: dict[str, str] | None = None):
    uploaded_blobs: list[str] = []
    input_path = os.path.join(input_folder)
    
    if not os.path.exists(input_path):
        print(f"Input folder not found: {input_path}")
        return uploaded_blobs
    
    # Find all JPEG files (both .jpeg and .jpg)
    jpeg_files: list[str] = []
    for file in os.listdir(input_path):
        if file.lower().endswith((".jpeg", ".jpg")):
            jpeg_files.append(file)
    
    if not jpeg_files:
        print(f"No JPEG images found in {input_path}")
        return uploaded_blobs
    
    print(f"Found {len(jpeg_files)} JPEG image(s) to upload")
    
    # Upload each image
    uploaded_names: list[str] = []
    for image_file in jpeg_files:
        image_path = os.path.join(input_path, image_file)
        target_name = image_name_map.get(image_file, image_file) if image_name_map else image_file
        blob_name = document_id + "/" + target_name
        try:
            image_blob = BlobClient.from_connection_string(
                conn_str=STORAGE_CONN_STR,
                container_name="image",
                blob_name=blob_name
            )
            
            # Upload the file (read in binary mode)
            with open(image_path, "rb") as f:
                image_blob.upload_blob(f, overwrite=True)
            
            print(f"Image uploaded: {blob_name}")
            uploaded_blobs.append(blob_name)
            uploaded_names.append(target_name)
        except Exception as e:
            print(f"Error uploading image {image_file}: {e}")
    
    return uploaded_blobs, uploaded_names

def delete_pdf_and_md(input_pdf_path: str):
    """Delete temporary PDF file and processing folders."""
    try:
        # Delete PDF file
        if os.path.exists(input_pdf_path):
            os.remove(input_pdf_path)
            print(f"Deleted temporary file: {input_pdf_path}")

        # Delete any previous marker output folder inside tmp (legacy)
        legacy_input_folder = os.path.join(TMP_DIR, "input")
        if os.path.exists(legacy_input_folder):
            shutil.rmtree(legacy_input_folder)
            print(f"Deleted temporary folder: {legacy_input_folder}")

        # Delete batched processing folder
        if os.path.exists(BATCHES_DIR):
            shutil.rmtree(BATCHES_DIR)
            print(f"Deleted temporary folder: {BATCHES_DIR}")

        # Delete final staging folder
        if os.path.exists(FINAL_DIR):
            shutil.rmtree(FINAL_DIR)
            print(f"Deleted temporary folder: {FINAL_DIR}")
    except Exception as cleanup_error:
        print(f"Warning: Error cleaning up temporary files: {cleanup_error}")


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


def _merge_meta_json(meta_parts: list[Any]) -> Any:
    if not meta_parts:
        return {}

    if all(isinstance(m, list) for m in meta_parts):
        merged_list: list[Any] = []
        for m in meta_parts:
            # m is a list here due to the all(...) check
            merged_list.extend(m)
        return merged_list

    if all(isinstance(m, dict) for m in meta_parts):
        merged: dict[str, Any] = {}
        for m in meta_parts:
            for k, v in m.items():
                if k not in merged:
                    merged[k] = v
                else:
                    if isinstance(merged[k], list) and isinstance(v, list):
                        merged[k].extend(v)
                    elif isinstance(merged[k], dict) and isinstance(v, dict):
                        # shallow merge for nested dicts
                        merged[k] = {**merged[k], **v}
                    else:
                        # keep first value for non-mergeable types
                        pass
        # The per-batch debug path isn't meaningful once merged
        merged["debug_data_path"] = "debug_data/merged"
        return merged

    # Mixed types: preserve as a list
    return {"batches": meta_parts}


def _rewrite_markdown_image_links(markdown_text: str, image_name_map: dict[str, str]) -> str:
    updated = markdown_text
    for old, new in image_name_map.items():
        updated = updated.replace(f"]({old})", f"]({new})")
        updated = updated.replace(f"](./{old})", f"](./{new})")
    return updated


def _ensure_clean_dir(path: str) -> None:
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)


def _merge_md_files(md_folder: str, merged_path: str) -> None:
    md_files = sorted([f for f in os.listdir(md_folder) if f.lower().endswith(".md")])
    with open(merged_path, "w", encoding="utf-8") as out:
        for i, filename in enumerate(md_files):
            file_path = os.path.join(md_folder, filename)
            with open(file_path, "r", encoding="utf-8") as inp:
                shutil.copyfileobj(inp, out)
            if i != len(md_files) - 1:
                out.write("\n\n")


def _merge_json_files(json_folder: str) -> Any:
    json_files = sorted([f for f in os.listdir(json_folder) if f.lower().endswith(".json")])
    parts: list[Any] = []
    for filename in json_files:
        file_path = os.path.join(json_folder, filename)
        with open(file_path, "r", encoding="utf-8") as f:
            parts.append(json.loads(f.read()))
    return _merge_meta_json(parts)

def update_document(document_id: str, images: list[str], parse_time: datetime.timedelta):
    db = next(get_db())
    document: Any = db.query(Document).filter(Document.document_id == document_id).first()
    if document:
        print(f"Document found: {document_id}")
        document.is_active = True
        document.markdown_parse_time = round(parse_time.total_seconds(), 2)
        document.images = images
        document.updated_at = datetime.datetime.now()
        db.commit()
        db.close()
        return True
    else:
        print(f"Document not found: {document_id}")
        db.close()
        return False

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
        merged_meta_json = json.dumps(merged_meta, ensure_ascii=False)

        # Upload merged Markdown + merged JSON
        upload_md(blob_name, markdown_content=merged_markdown, json_content=merged_meta_json)

        update_document(document_id, uploaded_image_names, parse_time)
        
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
                    #queue.update_message(msg, visibility_timeout=30)
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