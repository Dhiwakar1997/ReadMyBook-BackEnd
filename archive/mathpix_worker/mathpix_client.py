"""Mathpix PDF-to-Markdown API client.

Handles: submit, async polling, zip download, cleanup.
Uses asyncio for submit + wait_for_completion to avoid blocking threads.
A bounded semaphore limits concurrent Mathpix API operations.
"""

import os
import json
import shutil
import asyncio
import zipfile
from dataclasses import dataclass, field

import httpx


MATHPIX_BASE_URL = "https://api.mathpix.com/v3/pdf"

TMP_DIR = os.getenv("TMP_DIR", "tmp")
TEST_OUTPUT_DIR = os.path.join(TMP_DIR, "mathpix_test_output")

# Limit concurrent Mathpix operations to avoid exhausting threads / API rate limits
MAX_CONCURRENT_JOBS = int(os.getenv("MATHPIX_MAX_CONCURRENT_JOBS", "3"))
_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    """Lazy-init semaphore (must be created inside a running event loop)."""
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
    return _semaphore


@dataclass
class StreamedPage:
    """A single page result from the SSE stream."""
    page_idx: int
    text: str


@dataclass
class MathpixResult:
    """Aggregated result from a Mathpix conversion."""
    pdf_id: str
    pages: list[StreamedPage]
    merged_markdown: str
    images_dir: str | None = None
    image_filenames: list[str] = field(default_factory=list)
    num_pages: int = 0


class MathpixClient:
    """Mathpix API client with async submit + poll, sync download."""

    def __init__(
        self,
        app_id: str | None = None,
        app_key: str | None = None,
        timeout: float = 600.0,
        poll_interval: float = 5.0,
    ):
        self.app_id = app_id or os.getenv("MATHPIX_APP_ID", "")
        self.app_key = app_key or os.getenv("MATHPIX_APP_KEY", "")
        self.timeout = timeout
        self.poll_interval = poll_interval

        if not self.app_id or not self.app_key:
            raise RuntimeError("MATHPIX_APP_ID and MATHPIX_APP_KEY must be set")

        self._headers = {
            "app_id": self.app_id,
            "app_key": self.app_key,
        }

    # ── Async: submit + poll ─────────────────────────────────────────────

    async def async_submit_pdf(self, pdf_path: str) -> str:
        """Submit a PDF file to Mathpix for conversion (async).

        Returns the pdf_id for tracking.
        """
        options = {
            "conversion_formats": {"md.zip": True},
            # "streaming": True,  # disabled: using zip as primary method
        }

        with open(pdf_path, "rb") as f:
            file_bytes = f.read()

        files = {"file": (os.path.basename(pdf_path), file_bytes, "application/pdf")}
        data = {"options_json": json.dumps(options)}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                MATHPIX_BASE_URL,
                headers=self._headers,
                files=files,
                data=data,
            )
            response.raise_for_status()

        result = response.json()
        pdf_id = result.get("pdf_id")
        if not pdf_id:
            raise ValueError(f"Mathpix submit did not return pdf_id: {result}")

        return pdf_id

    async def async_get_status(self, pdf_id: str) -> dict:
        """Check processing status (async)."""
        url = f"{MATHPIX_BASE_URL}/{pdf_id}"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=self._headers)
            response.raise_for_status()
        return response.json()

    async def async_wait_for_completion(self, pdf_id: str) -> dict:
        """Poll status until completed or error (async, non-blocking sleep)."""
        while True:
            status = await self.async_get_status(pdf_id)
            state = status.get("status", "")
            print(
                f"  [STATUS] pdf_id={pdf_id} status={state} "
                f"percent={status.get('percent_done', 0)}"
            )

            if state == "completed":
                return status
            if state == "error":
                raise RuntimeError(
                    f"Mathpix processing failed: {status.get('error', 'unknown')}"
                )
            await asyncio.sleep(self.poll_interval)

    async def async_submit_and_wait(self, pdf_path: str) -> tuple[str, dict]:
        """Submit a PDF and wait for completion under the concurrency semaphore.

        Returns (pdf_id, status_dict).
        """
        sem = _get_semaphore()
        async with sem:
            print(f"[MATHPIX] Semaphore acquired (max {MAX_CONCURRENT_JOBS} concurrent)")
            pdf_id = await self.async_submit_pdf(pdf_path)
            print(f"[MATHPIX] Submitted. pdf_id={pdf_id}")
            status = await self.async_wait_for_completion(pdf_id)
            return pdf_id, status

    # submit_and_wait sync wrapper removed — the worker loop is now async,
    # so process_document calls async_submit_and_wait directly.

    # ── Test output helpers ──────────────────────────────────────────────

    def _get_test_dir(self, pdf_id: str) -> str:
        """Get the test output directory for a given pdf_id, creating it if needed."""
        test_dir = os.path.join(TEST_OUTPUT_DIR, pdf_id)
        os.makedirs(test_dir, exist_ok=True)
        return test_dir

    # ── SSE Stream (disabled — kept for future use) ──────────────────────

    # def stream_pages(self, pdf_id: str) -> list[StreamedPage]:
    #     """Connect to the SSE stream and collect page-by-page results.
    #
    #     Pages may arrive out of order. Returns list sorted by page_idx.
    #     Each page is saved to disk for test purposes.
    #     """
    #     url = f"{MATHPIX_BASE_URL}/{pdf_id}/stream"
    #     pages: dict[int, StreamedPage] = {}
    #
    #     test_dir = self._get_test_dir(pdf_id)
    #     pages_dir = os.path.join(test_dir, "pages")
    #     os.makedirs(pages_dir, exist_ok=True)
    #
    #     with httpx.Client(timeout=httpx.Timeout(self.timeout, read=None)) as client:
    #         with client.stream("GET", url, headers=self._headers) as response:
    #             response.raise_for_status()
    #             buffer = ""
    #             for chunk in response.iter_text():
    #                 buffer += chunk
    #                 while "\n\n" in buffer:
    #                     raw_event, buffer = buffer.split("\n\n", 1)
    #                     for line in raw_event.strip().split("\n"):
    #                         if line.startswith("data: "):
    #                             json_str = line[6:]
    #                             try:
    #                                 event_data = json.loads(json_str)
    #                             except json.JSONDecodeError:
    #                                 continue
    #
    #                             page_idx = event_data.get("page_idx")
    #                             text = event_data.get("text", "")
    #
    #                             if page_idx is not None:
    #                                 pages[page_idx] = StreamedPage(
    #                                     page_idx=page_idx,
    #                                     text=text,
    #                                 )
    #
    #                                 page_path = os.path.join(pages_dir, f"page_{page_idx:04d}.md")
    #                                 with open(page_path, "w", encoding="utf-8") as pf:
    #                                     pf.write(text)
    #
    #                                 print(f"  [SSE] Received page {page_idx} -> {page_path}")
    #
    #     sorted_pages = sorted(pages.values(), key=lambda p: p.page_idx)
    #     print(f"  [SSE] Stream complete: {len(sorted_pages)} pages saved to {pages_dir}")
    #     return sorted_pages

    # ── Sync: status check (kept as utility) ─────────────────────────────

    def get_status(self, pdf_id: str) -> dict:
        """Check processing status (sync)."""
        url = f"{MATHPIX_BASE_URL}/{pdf_id}"
        with httpx.Client(timeout=30) as client:
            response = client.get(url, headers=self._headers)
            response.raise_for_status()
        return response.json()

    # ── Sync: download zip ───────────────────────────────────────────────

    def download_md_zip(self, pdf_id: str, output_dir: str) -> tuple[str, list[str]]:
        """Download md.zip and extract it.

        The zip is also saved to the test output directory for inspection.

        Returns:
            (extracted_dir, image_filenames)
        """
        url = f"{MATHPIX_BASE_URL}/{pdf_id}.md.zip"

        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(url, headers=self._headers)
            response.raise_for_status()

        zip_bytes = response.content

        # Save zip to working output_dir for extraction
        zip_path = os.path.join(output_dir, f"{pdf_id}.md.zip")
        with open(zip_path, "wb") as f:
            f.write(zip_bytes)

        # Save a copy to the test directory for inspection
        test_dir = self._get_test_dir(pdf_id)
        test_zip_path = os.path.join(test_dir, f"{pdf_id}.md.zip")
        with open(test_zip_path, "wb") as f:
            f.write(zip_bytes)
        print(f"  [ZIP] Test copy saved to {test_zip_path}")

        extract_dir = os.path.join(output_dir, "md_extracted")
        os.makedirs(extract_dir, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)

        image_extensions = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
        image_filenames = []
        for root, _dirs, files in os.walk(extract_dir):
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext in image_extensions:
                    image_filenames.append(
                        os.path.relpath(os.path.join(root, fname), extract_dir)
                    )

        print(f"  [ZIP] Extracted {len(image_filenames)} images from md.zip")
        return extract_dir, sorted(image_filenames)

    # ── Sync: cleanup ────────────────────────────────────────────────────

    def delete_pdf(self, pdf_id: str) -> bool:
        """Delete the PDF from Mathpix servers and clean up local test artifacts."""
        url = f"{MATHPIX_BASE_URL}/{pdf_id}"
        try:
            with httpx.Client(timeout=30) as client:
                response = client.delete(url, headers=self._headers)
                response.raise_for_status()
            print(f"  [CLEANUP] Deleted pdf_id={pdf_id} from Mathpix")
        except Exception as e:
            print(f"  [CLEANUP] Warning: failed to delete pdf_id={pdf_id}: {e}")
            return False

        # Clean up local test output (pages + zip)
        test_dir = os.path.join(TEST_OUTPUT_DIR, pdf_id)
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir, ignore_errors=True)
            print(f"  [CLEANUP] Removed test artifacts: {test_dir}")

        return True
