"""
Thin test wrapper around the production PDF image extractor.

Usage
-----
    python extract_pdf_images_with_position.py [path_to_pdf]
"""

import logging
import sys
import time
from pathlib import Path

from worker_v2.image_extractor import extract_images_with_positions


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s | %(message)s",
                        datefmt="%H:%M:%S")

    script_dir = Path(__file__).resolve().parent
    pdf = Path(sys.argv[1]) if len(sys.argv) > 1 else script_dir / "test.pdf"

    start = time.perf_counter()
    results = extract_images_with_positions(str(pdf), str(script_dir / "extracted_images"))
    print(f"Extracted {len(results)} image entries in {time.perf_counter() - start:.2f}s")
