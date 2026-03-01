import hashlib

from pypdf import PdfReader


def get_file_hash(filepath: str) -> str:
    """Get SHA-256 hash of the raw file bytes."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def get_text_per_page(filepath: str) -> list[str]:
    """Extract text from each page of a PDF."""
    reader = PdfReader(filepath)
    return [page.extract_text() or "" for page in reader.pages]


def compare_pdfs(pdf1_path: str, pdf2_path: str) -> dict:
    """Compare two PDFs and return a detailed result."""

    result = {
        "identical_bytes": False,
        "same_page_count": False,
        "pages_with_differences": [],
        "summary": "",
    }

    # --- Check 1: byte-level comparison ---
    hash1 = get_file_hash(pdf1_path)
    hash2 = get_file_hash(pdf2_path)
    result["identical_bytes"] = hash1 == hash2
    result["hash1"]=hash1
    result["hash2"]=hash2

    if result["identical_bytes"]:
        result["summary"] = "Files are byte-for-byte identical."
        result["same_page_count"] = True
        return result

    # --- Check 2: page count ---
    pages1 = get_text_per_page(pdf1_path)
    pages2 = get_text_per_page(pdf2_path)
    result["same_page_count"] = len(pages1) == len(pages2)

    # --- Check 3: per-page text comparison ---
    max_pages = max(len(pages1), len(pages2))
    for i in range(max_pages):
        text1 = pages1[i] if i < len(pages1) else "<missing page>"
        text2 = pages2[i] if i < len(pages2) else "<missing page>"
        if text1 != text2:
            result["pages_with_differences"].append(i + 1)  # 1-based

    if not result["pages_with_differences"]:
        result["summary"] = "Files differ in binary content but have identical text on every page."
    else:
        diff_pages = result["pages_with_differences"]
        result["summary"] = (
            f"Text differs on {len(diff_pages)} page(s): {diff_pages}. "
            f"PDF1 has {len(pages1)} page(s), PDF2 has {len(pages2)} page(s)."
        )

    return result


if __name__ == "__main__":
    pdf1 = "file3.pdf"
    pdf2 = "file2.pdf"

    result = compare_pdfs(pdf1, pdf2)

    print(f"\nByte-identical : {result['identical_bytes']}")
    print(f"HASH 1 : {result['hash1']}")
    print(f"HASH 2 : {result['hash2']}")
    print(f"Same page count: {result['same_page_count']}")
    if result["pages_with_differences"]:
        print(f"Different pages: {result['pages_with_differences']}")
    print(f"\nSummary: {result['summary']}")
