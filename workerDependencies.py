"""Warm the Marker/Surya model caches during the Docker build.

This script is invoked in Dockerfile.worker to download the heavy assets that
`marker_single` pulls the first time it runs. We generate a tiny PDF, run the
CLI once (matching the worker's `--disable_ocr` flag), and keep the caches
inside the image so production runs stay offline-friendly and fast.
"""

import base64
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


# Minimal valid single-page PDF ("Hello World") encoded as base64 to avoid
# extra build-time dependencies.
SAMPLE_PDF_BASE64 = (
	"JVBERi0xLjMKJcTl8uXrp/Og0MTGCjEgMCBvYmoKPDwvVHlwZS9DYXRhbG9nL1BhZ2VzIDIg"
	"MCBSCj4+CmVuZG9iagoKMiAwIG9iago8PC9UeXBlL1BhZ2VzL0tpZHNbMyAwIFJdL0NvdW50"
	"IDEKPj4KZW5kb2JqCgozIDAgb2JqCjw8L1R5cGUvUGFnZS9QYXJlbnQgMiAwIFIvTWVkaWFC"
	"b3ggWzAgMCA2MTIgNzkyXS9Db250ZW50cyA0IDAgUi9SZXNvdXJjZXMgPDwvRm9udCA8PC9G"
	"MCA1IDAgUj4+Pj4KPj4KZW5kb2JqCgo0IDAgb2JqCjw8L0xlbmd0aCAzNSAwIFI+PnN0cmVh"
	"bQpCBiAvRjAgMjQgVGYgMTAwIDcwMCBUZCAoSGVsbG8gV29ybGQpIFRqCmVuZHN0cmVhbQpl"
	"bmRvYmoKCjUgMCBvYmoKPDwvVHlwZS9Gb250L1N1YnR5cGUvVHlwZTEvTmFtZS9GMC9CYXNl"
	"Rm9udC9IZWx2ZXRpY2E+PgplbmRvYmoKCnhyZWYKMCA2CjAwMDAwMDAwMDAgNjU1MzUgZgow"
	"MDAwMDAwMDExIDAwMDAwIG4KMDAwMDAwMDA3MCAwMDAwMCBuCjAwMDAwMDAxNTYgMDAwMDAg"
	"bgowMDAwMDAwMzUwIDAwMDAwIG4KMDAwMDAwMDQ1NSAwMDAwMCBuCnRyYWlsZXIKPDwvU2l6"
	"ZSA2L1Jvb3QgMSAwIFIvSW5mbyA4IDAgUgovSUQgWzxDMDM2RUQ2RTFCODI1QUIzRjAyM0M3"
	"MjNFQzEwMzNCQz48QzAzNkVENkUxQjgyNUFCM0YwMjNDNzIzRUMxMDMzQkM+XT4+CnN0YXJ0"
	"eHJlZgo1NTcKJSVFT0YK"
)


def allow_online_model_downloads() -> None:
	"""Temporarily allow huggingface/transformers to fetch models."""

	# Dockerfile sets HF_HUB_OFFLINE=1 for runtime; override during warmup.
	os.environ["HF_HUB_OFFLINE"] = "0"
	os.environ["TRANSFORMERS_OFFLINE"] = "0"


def ensure_cache_dirs() -> None:
	"""Create cache folders declared in Dockerfile so downloads persist."""

	datalab_cache = os.environ.get("DATALAB_CACHE_DIR", "/root/.cache/datalab")
	torch_home = os.environ.get("TORCH_HOME", "/root/.cache/torch")
	Path(datalab_cache).mkdir(parents=True, exist_ok=True)
	Path(torch_home).mkdir(parents=True, exist_ok=True)


def write_sample_pdf(tmp_dir: Path) -> Path:
	"""Write the embedded PDF to disk and return its path."""

	pdf_path = tmp_dir / "warmup.pdf"
	pdf_path.write_bytes(base64.b64decode(SAMPLE_PDF_BASE64))
	return pdf_path


def warm_marker_models(pdf_path: Path, output_dir: Path) -> None:
	"""Run marker_single once to trigger model downloads."""

	cmd = [
		"marker_single",
		str(pdf_path),
		"--output_dir",
		str(output_dir),
		"--disable_ocr",
	]
	print(f"Running: {' '.join(cmd)}")
	subprocess.run(cmd, check=True)


def main() -> None:
	allow_online_model_downloads()
	ensure_cache_dirs()

	tmp_root = Path(tempfile.mkdtemp(prefix="marker-warmup-"))
	output_dir = tmp_root / "out"
	output_dir.mkdir(parents=True, exist_ok=True)

	try:
		pdf_path = write_sample_pdf(tmp_root)
		warm_marker_models(pdf_path, output_dir)
		print("Marker dependencies downloaded successfully.")
	except FileNotFoundError as exc:
		print("marker_single not found. Make sure marker-pdf is installed.")
		raise exc
	finally:
		# Keep caches but drop temporary test artifacts to keep the image small.
		shutil.rmtree(tmp_root, ignore_errors=True)

	# Pre-download fastembed BM25 model for vector search
	print("Downloading fastembed BM25 model...")
	from fastembed import SparseTextEmbedding
	SparseTextEmbedding("Qdrant/bm25")
	print("BM25 model downloaded successfully.")


if __name__ == "__main__":
	main()
