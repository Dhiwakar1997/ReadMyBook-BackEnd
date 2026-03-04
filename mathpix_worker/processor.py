"""Orchestration logic for Mathpix PDF conversion.

Async flow: submit (async) -> poll until done (async, yields to event loop) ->
post-process in thread (download zip, extract, upload, metadata, vector DB, billing).

Each document gets its own temp directory so concurrent jobs don't collide.
"""

import os
import re
import json
import asyncio
import datetime
import shutil

from pypdf import PdfReader

from core.db_client import get_worker_db
from documents.data.model import Document
from documents.data.repository import DocumentRepository
from users.data.model import User  # SQLAlchemy FK resolution

from worker.bolbHelper import (
    download_pdf,
    upload_md,
    upload_final_images,
    list_images_in_container,
)
from worker.filesHelper import _ensure_clean_dir, delete_pdf_and_md
from worker.metadataHelper import create_md_metadata
from worker.vectorHelper import push_data_to_vector_db

from mathpix_worker.mathpix_client import MathpixClient


TMP_DIR = os.getenv("TMP_DIR", "tmp")
MATHPIX_TMP_BASE = os.path.join(TMP_DIR, "mathpix")


def _rewrite_image_paths(markdown: str) -> str:
    """Rewrite Mathpix image references to flat filenames.

    Converts: ![](./images/filename.jpg) -> ![](filename.jpg)
    Also clears the alt-text for image blocks to keep them clean.
    """
    return re.sub(
        r"!\[([^\]]*)\]\(\./images/([^)]+)\)",
        r"![](\2)",
        markdown,
    )


def _post_process(
    client: MathpixClient,
    pdf_id: str,
    status: dict,
    document_id: str,
    blob_name: str,
    container_name: str,
    input_pdf_path: str,
) -> bool:
    """Sync post-processing: download zip, extract, upload, metadata, vector DB, billing.

    Runs inside asyncio.to_thread() so it doesn't block the event loop.
    Each call uses a per-document temp directory to avoid collisions.
    """
    doc_tmp_dir = os.path.join(MATHPIX_TMP_BASE, document_id)
    db = None

    try:
        db = next(get_worker_db())
        doc_repo = DocumentRepository(db)

        document = doc_repo.get_document_by_id(document_id)
        if not document:
            print(f"Document not found: {document_id}")
            return False

        num_pages = status.get("num_pages", 0)

        # 4. Download md.zip — contains markdown + images
        _ensure_clean_dir(doc_tmp_dir)
        extract_dir, image_filenames = client.download_md_zip(pdf_id, doc_tmp_dir)

        # 5. Extract markdown from the zip
        md_files = [
            f for f in os.listdir(extract_dir)
            if f.endswith(".md")
        ]
        if not md_files:
            raise FileNotFoundError(
                f"No .md file found in md.zip for pdf_id={pdf_id}"
            )

        md_source_path = os.path.join(extract_dir, md_files[0])
        with open(md_source_path, "r", encoding="utf-8") as f:
            merged_markdown = f.read()
        print(f"[MATHPIX] [{document_id}] Loaded markdown from {md_files[0]}")

        # 6. Rewrite image paths: "./images/filename.jpg" -> "filename.jpg"
        merged_markdown = _rewrite_image_paths(merged_markdown)

        # 7. Upload images to Azure blob
        if image_filenames:
            images_staging_dir = os.path.join(doc_tmp_dir, "images_staging")
            os.makedirs(images_staging_dir, exist_ok=True)

            for img_rel_path in image_filenames:
                src = os.path.join(extract_dir, img_rel_path)
                flat_name = os.path.basename(img_rel_path)
                dst = os.path.join(images_staging_dir, flat_name)

                if os.path.exists(dst):
                    name, ext = os.path.splitext(flat_name)
                    counter = 1
                    while os.path.exists(dst):
                        flat_name = f"{name}_{counter}{ext}"
                        dst = os.path.join(images_staging_dir, flat_name)
                        counter += 1

                shutil.copy2(src, dst)

            uploaded_image_names = upload_final_images(
                images_staging_dir, document_id
            )
            print(f"[MATHPIX] [{document_id}] Uploaded {len(uploaded_image_names)} images")

        # 8. Write merged markdown to temp file for metadata generation
        merged_md_path = os.path.join(doc_tmp_dir, "merged.md")
        with open(merged_md_path, "w", encoding="utf-8") as f:
            f.write(merged_markdown)

        # 9. Generate metadata
        print(f"[MATHPIX] [{document_id}] Generating metadata...")
        metadata = create_md_metadata(merged_md_path, input_pdf_path, {})
        metadata_json = json.dumps(metadata, ensure_ascii=False)
        print(
            f"[MATHPIX] [{document_id}] Metadata: "
            f"{metadata.get('content_count', 0)} contents, "
            f"{metadata.get('heading_count', 0)} headings"
        )

        # 10. Upload markdown + metadata JSON to blob
        final_blob_name = f"{document_id}/{document_id}.pdf"
        upload_md(
            final_blob_name,
            markdown_content=merged_markdown,
            json_content=metadata_json,
        )

        # 11. Update document model
        document.status = "active"
        document.updated_at = datetime.datetime.now()
        doc_repo.update_final_job_status(document_id, "completed")
        db.commit()

        # 12. Push to vector DB
        push_data_to_vector_db(metadata, document_id, document.owner_id, db=db)

        # 13. Billing — $0.0035/page + $0.0015/image
        try:
            reader = PdfReader(input_pdf_path)
            page_count = len(reader.pages)
        except Exception:
            page_count = num_pages or 1

        image_count = len(image_filenames) if image_filenames else 0

        try:
            from billing.service.balance_service import BalanceService
            billing_svc = BalanceService()
            try:
                billing_svc.deduct_mathpix_cost(
                    user_id=document.owner_id,
                    pages=page_count,
                    images=image_count,
                    document_id=document_id,
                )
                print(f"[MATHPIX] [{document_id}][billing] Deducted for {page_count} pages, {image_count} images")
            finally:
                billing_svc.close()
        except Exception as billing_exc:
            print(f"[MATHPIX] [{document_id}][billing] Deduction failed: {billing_exc}")

        # 14. Update document images from blob
        image_filenames_from_blob = list_images_in_container(document_id)
        if image_filenames_from_blob:
            document.images = image_filenames_from_blob
            db.commit()
            print(f"[MATHPIX] [{document_id}] {len(image_filenames_from_blob)} images in document model")

        # 15. Cleanup Mathpix server resource
        client.delete_pdf(pdf_id)

        return True

    except Exception as e:
        print(f"[MATHPIX] [{document_id}] Post-processing error: {e}")

        if db:
            try:
                doc_repo = DocumentRepository(db)
                doc_repo.set_status(document_id, "failed")
                doc_repo.update_final_job_status(document_id, "failed")
            except Exception:
                pass

        try:
            client.delete_pdf(pdf_id)
        except Exception:
            pass

        return False

    finally:
        if db is not None:
            db.close()

        # Clean up per-document temp directory
        if os.path.exists(doc_tmp_dir):
            shutil.rmtree(doc_tmp_dir, ignore_errors=True)

        # Clean up downloaded PDF
        if input_pdf_path:
            try:
                delete_pdf_and_md(input_pdf_path)
            except Exception:
                pass


async def process_document(document_id: str, blob_name: str, container_name: str) -> bool:
    """Full Mathpix conversion pipeline for a single document (async).

    Phase 1 (async): Submit PDF to Mathpix and poll until complete.
                     Yields to the event loop during polling sleeps so the
                     worker can pick up new messages concurrently.
    Phase 2 (threaded): Download zip, extract, upload, metadata, vector DB.
                        Runs in asyncio.to_thread() to avoid blocking the loop.
    """
    client = MathpixClient()
    pdf_id = None
    input_pdf_path = None

    try:
        # ── Phase 0: DB setup + download PDF ─────────────────────────────
        db = next(get_worker_db())
        doc_repo = DocumentRepository(db)

        document = doc_repo.get_document_by_id(document_id)
        if not document:
            print(f"Document not found: {document_id}")
            db.close()
            return False

        doc_repo.set_status(document_id, "processing")
        doc_repo.update_final_job_status(document_id, "processing")
        start_time = datetime.datetime.now()
        db.close()

        input_pdf_path = download_pdf(container_name, blob_name)
        print(f"[MATHPIX] [{document_id}] PDF downloaded: {input_pdf_path}")

        # ── Phase 1: async submit + poll (non-blocking) ──────────────────
        pdf_id, status = await client.async_submit_and_wait(input_pdf_path)
        num_pages = status.get("num_pages", 0)
        print(f"[MATHPIX] [{document_id}] Conversion complete. pdf_id={pdf_id}, pages={num_pages}")

        # ── SSE streaming disabled — using zip as primary method ─────────
        # pages = client.stream_pages(pdf_id)
        # print(f"[MATHPIX] Streamed {len(pages)} pages")
        # ─────────────────────────────────────────────────────────────────

        # ── Phase 2: sync post-processing in a thread ────────────────────
        success = await asyncio.to_thread(
            _post_process,
            client,
            pdf_id,
            status,
            document_id,
            blob_name,
            container_name,
            input_pdf_path,
        )

        end_time = datetime.datetime.now()
        total_seconds = (end_time - start_time).total_seconds()

        if success:
            # Update parse time
            db = next(get_worker_db())
            doc = DocumentRepository(db).get_document_by_id(document_id)
            if doc:
                doc.markdown_parse_time = round(total_seconds, 2)
                db.commit()
            db.close()
            print(f"[MATHPIX] [{document_id}] Complete in {total_seconds:.1f}s")

        return success

    except Exception as e:
        print(f"[MATHPIX] [{document_id}] Error: {e}")

        try:
            db = next(get_worker_db())
            repo = DocumentRepository(db)
            repo.set_status(document_id, "failed")
            repo.update_final_job_status(document_id, "failed")
            db.close()
        except Exception:
            pass

        if pdf_id:
            try:
                client.delete_pdf(pdf_id)
            except Exception:
                pass

        if input_pdf_path:
            try:
                delete_pdf_and_md(input_pdf_path)
            except Exception:
                pass

        return False
