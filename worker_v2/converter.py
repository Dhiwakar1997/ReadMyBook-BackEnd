"""
PDF-to-Markdown converter using PyMuPDF — no external APIs or ML models.

Detects headings (by font size), bold / italic / monospace inline
formatting, lists, code blocks, and tables from PyMuPDF layout data.
Inserts <!-- Page N --> markers for downstream page-aware processing.
"""

import fitz
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_BOLD_FLAG = 16
_ITALIC_FLAG = 2
_MONO_FLAG = 8
_MARGIN_PT = 55
_TABLE_OVERLAP_RATIO = 0.6


def _is_bold(span: dict) -> bool:
    return bool(span.get("flags", 0) & _BOLD_FLAG) or "bold" in span.get("font", "").lower()


def _is_italic(span: dict) -> bool:
    f = span.get("font", "").lower()
    return bool(span.get("flags", 0) & _ITALIC_FLAG) or "italic" in f or "oblique" in f


def _is_mono(span: dict) -> bool:
    f = span.get("font", "").lower()
    return bool(span.get("flags", 0) & _MONO_FLAG) or any(
        m in f for m in ("mono", "courier", "consol"))


def _survey_body_size(doc: fitz.Document) -> float:
    """Most common font size (weighted by char count) = body text size."""
    counter: Counter[float] = Counter()
    for page in doc:
        for block in page.get_text("dict", sort=True).get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    t = span.get("text", "").strip()
                    if t:
                        counter[round(span["size"], 1)] += len(t)
    return counter.most_common(1)[0][0] if counter else 12.0


def _heading_level(size: float, body: float) -> int:
    """Map font size to heading level (0 = body text)."""
    r = size / body if body else 1.0
    if r >= 2.0:
        return 1
    if r >= 1.5:
        return 2
    if r >= 1.25:
        return 3
    if r >= 1.1:
        return 4
    return 0


def _format_line(line: dict) -> tuple[str, float]:
    """Render one line's spans as markdown text.

    Returns (formatted_text, max_font_size_in_line).
    """
    groups: list[tuple[tuple[bool, bool, bool], str]] = []
    cur_fmt: tuple[bool, bool, bool] | None = None
    cur_parts: list[str] = []
    max_size = 0.0

    for span in line.get("spans", []):
        text = span.get("text", "")
        if not text:
            continue
        max_size = max(max_size, span.get("size", 0.0))
        fmt = (_is_bold(span), _is_italic(span), _is_mono(span))
        if fmt == cur_fmt:
            cur_parts.append(text)
        else:
            if cur_parts:
                groups.append((cur_fmt, "".join(cur_parts)))  # type: ignore[arg-type]
            cur_fmt = fmt
            cur_parts = [text]
    if cur_parts:
        groups.append((cur_fmt, "".join(cur_parts)))  # type: ignore[arg-type]

    parts: list[str] = []
    for (bold, italic, mono), text in groups:
        if not text:
            continue
        if mono:
            text = f"`{text}`"
        elif bold and italic:
            text = f"***{text}***"
        elif bold:
            text = f"**{text}**"
        elif italic:
            text = f"*{text}*"
        parts.append(text)

    return "".join(parts).strip(), max_size


def _join_lines(lines: list[str]) -> str:
    """Join paragraph lines, collapsing end-of-line hyphens."""
    out: list[str] = []
    for i, ln in enumerate(lines):
        if (ln.endswith("-") or ln.endswith("\u00ad")) and i + 1 < len(lines):
            nxt = lines[i + 1]
            if nxt and nxt[0].islower():
                out.append(ln.rstrip("-\u00ad"))
                continue
        out.append(ln)
        if i < len(lines) - 1:
            out.append(" ")
    return "".join(out).strip()


_LIST_RE = re.compile(
    r"^(\s*[-\u2022\u00b7\u25aa\u25b8\u25ba]\s+"
    r"|\s*\d+[.)]\s+"
    r"|\s*[a-zA-Z][.)]\s+)"
)


def _is_list_item(text: str) -> bool:
    return bool(_LIST_RE.match(text))


def _looks_like_page_number(text: str) -> bool:
    """Heuristic: standalone page numbers or 'N | Chapter ...' footers."""
    t = text.strip()
    if re.match(r"^\d{1,4}$", t):
        return True
    if re.match(r"^\d{1,4}\s*\|", t) or re.search(r"\|\s*\d{1,4}\s*$", t):
        return True
    return False


def _to_rect(bbox: Any) -> fitz.Rect | None:
    try:
        rect = fitz.Rect(bbox)
    except Exception:
        return None
    if rect.is_empty or rect.is_infinite:
        return None
    return rect


def _is_block_inside_table(block_bbox: Any, table_rects: list[fitz.Rect]) -> bool:
    rect = _to_rect(block_bbox)
    if rect is None:
        return False

    block_area = max(rect.width * rect.height, 1.0)
    cx = (rect.x0 + rect.x1) / 2
    cy = (rect.y0 + rect.y1) / 2

    for table_rect in table_rects:
        if table_rect.x0 <= cx <= table_rect.x1 and table_rect.y0 <= cy <= table_rect.y1:
            return True

        overlap = rect & table_rect
        if overlap.is_empty:
            continue

        overlap_area = overlap.width * overlap.height
        if overlap_area / block_area >= _TABLE_OVERLAP_RATIO:
            return True

    return False


def _normalize_table_cell(cell: Any) -> str:
    if cell is None:
        return ""

    raw = str(cell).replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"\s+", " ", part).strip() for part in raw.split("\n")]
    text = "<br>".join(part for part in lines if part)
    return text.replace("|", r"\|")


def _table_to_markdown_lines(table: Any) -> list[str]:
    rows = table.extract() or []
    col_count = max(getattr(table, "col_count", 0), max((len(row) for row in rows), default=0))
    if col_count == 0:
        return []

    normalized_rows = []
    for row in rows:
        normalized = [_normalize_table_cell(cell) for cell in row[:col_count]]
        if len(normalized) < col_count:
            normalized.extend([""] * (col_count - len(normalized)))
        normalized_rows.append(normalized)

    header_obj = getattr(table, "header", None)
    header_names = []
    if header_obj is not None:
        header_names = [_normalize_table_cell(name) for name in getattr(header_obj, "names", [])]
        if len(header_names) < col_count:
            header_names.extend([""] * (col_count - len(header_names)))
        header_names = header_names[:col_count]

    if any(header_names):
        header = header_names
        data_rows = normalized_rows[1:] if not getattr(header_obj, "external", False) else normalized_rows
    else:
        header = normalized_rows[0] if normalized_rows else [""] * col_count
        data_rows = normalized_rows[1:] if normalized_rows else []

    lines = [
        f"| {' | '.join(header)} |",
        f"| {' | '.join(['---'] * col_count)} |",
    ]
    lines.extend(f"| {' | '.join(row)} |" for row in data_rows)
    return lines


def _extract_table_entries(page: fitz.Page) -> list[dict[str, Any]]:
    if not hasattr(page, "find_tables"):
        return []

    if hasattr(fitz, "no_recommend_layout"):
        fitz.no_recommend_layout()

    try:
        table_finder = page.find_tables()
    except Exception as exc:
        log.debug("Page %s: table detection failed: %s", page.number + 1, exc)
        return []

    entries: list[dict[str, Any]] = []
    for table in getattr(table_finder, "tables", []):
        rect = _to_rect(getattr(table, "bbox", None))
        if rect is None:
            continue

        markdown_lines = _table_to_markdown_lines(table)
        if not markdown_lines:
            continue

        entries.append({
            "kind": "table",
            "x0": rect.x0,
            "y0": rect.y0,
            "rect": rect,
            "lines": markdown_lines,
        })

    return entries


def convert_pdf_to_markdown(pdf_path: str) -> str:
    """Convert *pdf_path* to a Markdown string."""
    pdf_path_p = Path(pdf_path)
    if not pdf_path_p.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path_p}")

    with fitz.open(str(pdf_path_p)) as doc:
        body_size = _survey_body_size(doc)
        total_pages = len(doc)
        log.info(f"Opened: {pdf_path_p.name} ({total_pages} pages, body {body_size}pt)")

        md: list[str] = []

        for page_num in range(total_pages):
            page = doc[page_num]
            page_h = page.rect.height
            md.append(f"<!-- Page {page_num + 1} -->")
            md.append("")

            page_dict = page.get_text("dict", sort=True)
            table_entries = _extract_table_entries(page)
            table_rects = [entry["rect"] for entry in table_entries]

            elements: list[dict[str, Any]] = list(table_entries)
            for block in page_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue

                bbox = block.get("bbox", (0, 0, 0, 0))
                rect = _to_rect(bbox)
                if rect is not None and _is_block_inside_table(bbox, table_rects):
                    continue

                elements.append({
                    "kind": "text",
                    "x0": rect.x0 if rect is not None else bbox[0],
                    "y0": rect.y0 if rect is not None else bbox[1],
                    "bbox": bbox,
                    "block": block,
                })

            elements.sort(key=lambda item: (item["y0"], item["x0"], 0 if item["kind"] == "table" else 1))

            for item in elements:
                if item["kind"] == "table":
                    md.extend(item["lines"])
                    md.append("")
                    continue

                block = item["block"]
                bbox = item["bbox"]

                line_texts: list[str] = []
                block_max_size = 0.0
                all_bold = True
                all_mono = True

                for line in block.get("lines", []):
                    text, mx = _format_line(line)
                    if not text:
                        continue
                    line_texts.append(text)
                    block_max_size = max(block_max_size, mx)
                    for span in line.get("spans", []):
                        if not span.get("text", "").strip():
                            continue
                        if not _is_bold(span):
                            all_bold = False
                        if not _is_mono(span):
                            all_mono = False

                if not line_texts:
                    continue

                joined = _join_lines(line_texts)

                in_margin = bbox[1] < _MARGIN_PT or bbox[3] > page_h - _MARGIN_PT
                if in_margin and _looks_like_page_number(joined):
                    continue

                hlevel = _heading_level(block_max_size, body_size)

                if hlevel == 0 and all_bold and len(joined) < 100:
                    hlevel = 4

                if hlevel > 0:
                    clean = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", joined)
                    clean = clean.strip().strip("`")
                    md.append(f"{'#' * hlevel} {clean}")
                    md.append("")

                elif all_mono and len(line_texts) > 1:
                    code = "\n".join(t.strip("`") for t in line_texts)
                    md.append("```")
                    md.append(code)
                    md.append("```")
                    md.append("")

                elif any(_is_list_item(t) for t in line_texts):
                    for t in line_texts:
                        md.append(t)
                    md.append("")

                else:
                    md.append(joined)
                    md.append("")

    log.info(f"Conversion done: {total_pages} pages")
    return "\n".join(md)
