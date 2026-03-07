"""
Extract images from PDFs with positional context using PyMuPDF.

Each extracted image is paired with the sentence/text block that
immediately precedes it in the document's reading order.  When an
image-only page has no preceding text, the last sentence from any
earlier page is used as fallback.
"""

import fitz
import logging
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)
_MAX_IMAGE_OCCURRENCES = 1000


class ImageLimitExceededError(ValueError):
    """Raised when a PDF contains too many image occurrences to process."""


def _text_blocks(page: fitz.Page) -> list[dict[str, Any]]:
    """Return text blocks on *page* with bbox and joined text."""
    blocks = []
    for block in page.get_text("dict", sort=True).get("blocks", []):
        bbox = block.get("bbox")
        if not bbox:
            continue
        spans_text = []
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                spans_text.append(span.get("text", ""))
        text = " ".join(spans_text).strip()
        if text:
            blocks.append({"bbox": bbox, "y0": bbox[1], "y1": bbox[3],
                           "x0": bbox[0], "x1": bbox[2], "text": text})
    return blocks


def _image_bboxes(page: fitz.Page) -> list[dict[str, Any]]:
    """Return embedded image occurrences on *page* with bbox and xref."""
    images = []
    for img_info in page.get_image_info(xrefs=True):
        bbox = img_info.get("bbox")
        xref = img_info.get("xref")
        if bbox is None or xref is None:
            continue
        images.append({"xref": xref,
                       "number": img_info.get("number"),
                       "bbox": bbox,
                       "y0": bbox[1], "y1": bbox[3],
                       "x0": bbox[0], "x1": bbox[2]})
    return images


def _count_image_occurrences(doc: fitz.Document) -> int:
    total = 0
    for page in doc:
        total += sum(
            1
            for img_info in page.get_image_info(xrefs=True)
            if img_info.get("bbox") is not None and img_info.get("xref") is not None
        )
    return total


def _preceding_sentence(ordered: list[dict], target: dict) -> str:
    """Walk *ordered* items and return the last text before *target* image."""
    sentence = ""
    for item in ordered:
        if (item["kind"] == "image"
                and item.get("number") == target.get("number")
                and item["y0"] == target["y0"]
                and item["x0"] == target["x0"]
                and item.get("xref") == target.get("xref")):
            break
        if item["kind"] == "text":
            sentence = item["text"]
    return sentence.strip()


def extract_images_with_positions(
    pdf_path: str,
    output_dir: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Extract every embedded image from *pdf_path* and save to *output_dir*.

    Returns a list of dicts, one per image, with keys:
        page, bbox, position, sentence_before, output_path, image_saved
    """
    pdf_path_p = Path(pdf_path)
    if not pdf_path_p.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path_p}")

    if output_dir is None:
        out_dir = pdf_path_p.parent / "extracted_images"
    else:
        out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with fitz.open(str(pdf_path_p)) as doc:
        total_image_occurrences = _count_image_occurrences(doc)
        if total_image_occurrences > _MAX_IMAGE_OCCURRENCES:
            raise ImageLimitExceededError(
                f"PDF has {total_image_occurrences} images; maximum supported is {_MAX_IMAGE_OCCURRENCES}"
            )

        results: list[dict[str, Any]] = []
        last_sentence = ""

        log.info(f"Opened PDF: {pdf_path_p.name} ({len(doc)} pages)")

        for page_num in range(len(doc)):
            page = doc[page_num]
            page_no = page_num + 1

            text_blocks = _text_blocks(page)
            image_infos = _image_bboxes(page)

            if not image_infos:
                if text_blocks:
                    last_sentence = text_blocks[-1]["text"].strip()
                continue

            ordered: list[dict[str, Any]] = []
            for b in text_blocks:
                ordered.append({"kind": "text", "y0": b["y0"],
                                "x0": b["x0"], "text": b["text"]})
            for img in image_infos:
                ordered.append({"kind": "image", "y0": img["y0"],
                                "x0": img["x0"], "xref": img["xref"],
                                "number": img.get("number"),
                                "bbox": img["bbox"], "page_num": page_no})
            ordered.sort(key=lambda x: (x["y0"], x["x0"]))

            for img in image_infos:
                sentence = _preceding_sentence(ordered, img)
                if not sentence and last_sentence:
                    sentence = last_sentence

                try:
                    base_image = doc.extract_image(img["xref"])
                    image_bytes = base_image["image"]
                    ext = base_image["ext"]
                except Exception as exc:
                    log.debug(f"Page {page_no}: failed to extract xref {img['xref']} - {exc}")
                    results.append({"page": page_no, "bbox": img["bbox"],
                                    "sentence_before": sentence,
                                    "error": str(exc), "image_saved": False})
                    continue

                idx = sum(1 for r in results
                          if r.get("page") == page_no and "error" not in r)
                safe = "".join(c if c.isalnum() or c in "_-" else "_"
                               for c in sentence[:50]).strip("_") or "image"
                filename = f"page{page_no}_{idx:02d}_{safe[:30]}.{ext}"
                out_path = out_dir / filename
                out_path.write_bytes(image_bytes)

                results.append({
                    "page": page_no,
                    "bbox": img["bbox"],
                    "position": {"x0": img["x0"], "y0": img["y0"],
                                 "x1": img["x1"], "y1": img["y1"],
                                 "width_pt": img["x1"] - img["x0"],
                                 "height_pt": img["y1"] - img["y0"]},
                    "sentence_before": sentence,
                    "output_path": str(out_path),
                    "image_saved": True,
                })

            for item in reversed(ordered):
                if item["kind"] == "text" and item.get("text", "").strip():
                    last_sentence = item["text"].strip()
                    break

        total_pages = len(doc)

    saved = [r for r in results if r.get("image_saved")]
    log.info(f"Extracted {len(saved)} images from {total_pages} pages")
    return results
