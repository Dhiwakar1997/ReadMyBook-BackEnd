"""
Thin test wrapper around the production PDF-to-Markdown converter.

Usage
-----
    python pdf_to_markdown.py [path_to_pdf]
"""

import logging
import sys
import time
from pathlib import Path

from worker_v2.converter import convert_pdf_to_markdown


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s | %(message)s",
                        datefmt="%H:%M:%S")

    script_dir = Path(__file__).resolve().parent
    pdf = Path(sys.argv[1]) if len(sys.argv) > 1 else script_dir / "test.pdf"
    out = pdf.with_suffix(".md")

    start = time.perf_counter()
    result = convert_pdf_to_markdown(str(pdf))
    out.write_text(result, encoding="utf-8")

    elapsed = time.perf_counter() - start
    print(f"Wrote {out} ({len(result):,} chars) in {elapsed:.2f}s")
