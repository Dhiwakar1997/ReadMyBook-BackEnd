"""
End-to-end pipeline: PDF -> Markdown with embedded image references.

Steps
-----
1. Convert PDF to Markdown locally (PyMuPDF font analysis)
2. Extract images from the same PDF with positional context (PyMuPDF)
3. Match each image to its location in the Markdown via page-aware
   sentence matching, then insert image tags
4. Write the final Markdown with local image links

Usage
-----
    python pdf_to_md_with_images.py [path_to_pdf]

Requires
--------
    pip install pymupdf
"""

import logging
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

from extract_pdf_images_with_position import extract_images_with_positions
from pdf_to_markdown import convert_pdf_to_markdown

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pipeline")


# ── Step 3: page-aware image matching and insertion ─────────────────────────

def _normalize(text: str) -> str:
    """Strip markdown formatting, unicode hyphens; collapse whitespace."""
    text = re.sub(r'[*_#\[\](){}|`>~\\]', '', text)
    text = re.sub(r'[\u2010-\u2015\u2212\xad\u00ad]', '', text)
    text = re.sub(r'-\s*\n\s*', '', text)
    return re.sub(r'\s+', ' ', text).strip().lower()


def _search_chunks(text: str, size: int = 3, max_n: int = 8) -> list[str]:
    """Produce overlapping word-group chunks for fuzzy matching."""
    words = text.split()
    if len(words) <= size:
        return [text] if text.strip() else []
    step = max(1, (len(words) - size) // (max_n - 1))
    chunks: list[str] = []
    for i in range(0, len(words) - size + 1, step):
        chunks.append(" ".join(words[i:i + size]))
        if len(chunks) >= max_n:
            break
    return chunks


def _parse_page_sections(md_lines: list[str]) -> dict[int, tuple[int, int]]:
    """Map PDF page numbers to (start_line, end_line) in the markdown."""
    markers: list[tuple[int, int]] = []
    for i, line in enumerate(md_lines):
        for m in re.finditer(r'<!--\s*Page\s+(\d+)\s*-->', line):
            markers.append((int(m.group(1)), i))

    sections: dict[int, tuple[int, int]] = {}
    for idx, (pg, start) in enumerate(markers):
        end = markers[idx + 1][1] - 1 if idx + 1 < len(markers) else len(md_lines) - 1
        sections[pg] = (start, end)
    return sections


def _build_paragraphs(md_lines: list[str]) -> list[dict[str, Any]]:
    """Group consecutive non-blank lines into paragraphs."""
    paragraphs: list[dict[str, Any]] = []
    buf: list[str] = []
    for i, line in enumerate(md_lines):
        if line.strip() == "":
            if buf:
                paragraphs.append({
                    "norm": _normalize(" ".join(buf)),
                    "end_line": i - 1,
                })
                buf = []
        else:
            buf.append(line)
    if buf:
        paragraphs.append({
            "norm": _normalize(" ".join(buf)),
            "end_line": len(md_lines) - 1,
        })
    return paragraphs


def _find_section_range(
    page: int,
    page_sections: dict[int, tuple[int, int]],
    total_lines: int,
) -> tuple[int, int]:
    """Return (start, end) line range for a page, searching nearby if needed."""
    if page in page_sections:
        return page_sections[page]
    for delta in [-1, 1, -2, 2, -3, 3]:
        if page + delta in page_sections:
            return page_sections[page + delta]
    return (0, total_lines - 1)


def _match_paragraph(
    sentence_norm: str,
    paragraphs: list[dict[str, Any]],
    section_start: int,
    section_end: int,
) -> Optional[dict[str, Any]]:
    """Find the best matching paragraph within a line range."""
    chunks = _search_chunks(sentence_norm, size=3, max_n=8)
    if not chunks:
        return None

    candidates = [p for p in paragraphs
                  if section_start <= p["end_line"] <= section_end]

    best: Optional[dict[str, Any]] = None
    best_score = 0
    for p in candidates:
        score = sum(1 for c in chunks if c in p["norm"])
        if score > best_score:
            best_score = score
            best = p

    threshold = max(1, len(chunks) // 4)
    return best if best_score >= threshold else None


def insert_images_into_markdown(
    md_text: str,
    image_results: list[dict[str, Any]],
    images_rel_dir: str,
) -> str:
    """Insert markdown image tags at the correct positions."""
    _ = images_rel_dir

    md_lines = md_text.split("\n")
    page_sections = _parse_page_sections(md_lines)
    paragraphs = _build_paragraphs(md_lines)

    insertions: dict[int, list[str]] = {}
    matched = 0
    fallback_count = 0

    for img in image_results:
        if not img.get("image_saved"):
            continue

        img_name = Path(img["output_path"]).name
        encoded_name = quote(img_name)
        tag = f"\n![{Path(img_name).stem}]({encoded_name})\n"

        page = img["page"]
        sentence = img.get("sentence_before", "").strip()
        norm_sentence = _normalize(sentence) if sentence else ""

        sec_start, sec_end = _find_section_range(page, page_sections, len(md_lines))

        target_para = None

        if norm_sentence:
            target_para = _match_paragraph(norm_sentence, paragraphs, sec_start, sec_end)

        if target_para is None and norm_sentence and page - 1 in page_sections:
            prev_start, _ = page_sections[page - 1]
            target_para = _match_paragraph(norm_sentence, paragraphs, prev_start, sec_end)

        if target_para is None and norm_sentence and page - 2 in page_sections:
            prev2_start, _ = page_sections[page - 2]
            target_para = _match_paragraph(norm_sentence, paragraphs, prev2_start, sec_end)

        if target_para is not None:
            insertions.setdefault(target_para["end_line"], []).append(tag)
            matched += 1
        else:
            insertions.setdefault(sec_end, []).append(tag)
            fallback_count += 1

    total = matched + fallback_count
    log.info(f"  Matched {matched}/{total} images by sentence")
    log.info(f"  Placed {fallback_count}/{total} images at page-end (fallback)")

    result: list[str] = []
    for i, line in enumerate(md_lines):
        result.append(line)
        for t in insertions.get(i, []):
            result.append(t)

    return "\n".join(result)


# ── Pipeline orchestration ──────────────────────────────────────────────────

def run_pipeline(
    pdf_path: str,
    images_dir: str,
    output_md_path: str,
    images_rel_dir: str = "extracted_images",
) -> None:
    total_start = time.perf_counter()

    log.info("=" * 60)
    log.info("  PDF -> Markdown with Images Pipeline")
    log.info("=" * 60)
    log.info(f"  PDF           : {pdf_path}")
    log.info(f"  Images dir    : {images_dir}")
    log.info(f"  Output        : {output_md_path}")

    # ── Step 1 ──────────────────────────────────────────────────────────
    log.info("-" * 60)
    log.info("STEP 1 : PDF -> Markdown  (local PyMuPDF)")
    t = time.perf_counter()
    md_text = convert_pdf_to_markdown(pdf_path)
    log.info(f"  {len(md_text):,} chars | {md_text.count(chr(10)):,} lines")
    log.info(f"  Step 1 done in {time.perf_counter() - t:.2f}s")

    raw_path = Path(output_md_path).with_name("raw_converted.md")
    raw_path.write_text(md_text, encoding="utf-8")
    log.info(f"  Raw markdown saved: {raw_path.name}")

    # ── Step 2 ──────────────────────────────────────────────────────────
    log.info("-" * 60)
    log.info("STEP 2 : Extract images with positional context  (PyMuPDF)")
    t = time.perf_counter()
    image_results = extract_images_with_positions(pdf_path, images_dir)
    saved = [r for r in image_results if r.get("image_saved")]
    pages_with_images = len({r["page"] for r in saved})
    log.info(f"  {len(saved)} images across {pages_with_images} pages")
    log.info(f"  Step 2 done in {time.perf_counter() - t:.2f}s")

    # ── Step 3 ──────────────────────────────────────────────────────────
    log.info("-" * 60)
    log.info("STEP 3 : Insert image tags into markdown")
    t = time.perf_counter()
    final_md = insert_images_into_markdown(md_text, image_results, images_rel_dir)
    log.info(f"  Step 3 done in {time.perf_counter() - t:.2f}s")

    # ── Step 4 ──────────────────────────────────────────────────────────
    log.info("-" * 60)
    log.info("STEP 4 : Write final markdown")
    Path(output_md_path).write_text(final_md, encoding="utf-8")
    log.info(f"  {len(final_md):,} chars | {final_md.count(chr(10)):,} lines")

    elapsed = time.perf_counter() - total_start
    log.info("=" * 60)
    log.info(f"  Pipeline complete in {elapsed:.2f}s")
    log.info("=" * 60)


# ── CLI entry-point ─────────────────────────────────────────────────────────

def main() -> None:
    script_dir = Path(__file__).resolve().parent

    pdf_path = script_dir / "test.pdf"
    if len(sys.argv) > 1:
        pdf_path = Path(sys.argv[1])

    run_pipeline(
        pdf_path=str(pdf_path),
        images_dir=str(script_dir / "extracted_images"),
        output_md_path=str(script_dir / "output_with_images.md"),
        images_rel_dir="extracted_images",
    )


if __name__ == "__main__":
    main()
