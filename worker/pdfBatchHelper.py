import os

from pypdf import PdfReader, PdfWriter

TMP_DIR = os.getenv("TMP_DIR", "tmp")
BATCHES_DIR = os.path.join(TMP_DIR, "batches")

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