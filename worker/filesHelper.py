import os
import shutil
import json

from typing import Any

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