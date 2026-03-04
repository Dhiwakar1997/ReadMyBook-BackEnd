import os

from azure.storage.blob import BlobClient, ContainerClient

QUEUE_NAME = os.getenv("QUEUE_NAME","")
STORAGE_CONN_STR = os.getenv("AZURE_CONNECTION_STRING","")
TMP_DIR = os.getenv("TMP_DIR", "tmp")


def download_pdf(container_name: str, blob_name: str) -> str:

    blob_client = BlobClient.from_connection_string(
        conn_str=STORAGE_CONN_STR,
        container_name=container_name,
        blob_name=blob_name
    )
    
    pdf_bytes = blob_client.download_blob().readall()
    os.makedirs(TMP_DIR, exist_ok=True)
    input_pdf_path = os.path.join(TMP_DIR, "input.pdf")
    
    with open(input_pdf_path, "wb") as f:
        f.write(pdf_bytes)
    print(f"PDF downloaded successfully to {input_pdf_path}")
    
    return input_pdf_path

def upload_md(blob_name: str, *, markdown_content: str, json_content: str) -> bool:
    output_blob_name = os.path.splitext(blob_name)[0] + ".md"
    output_blob = BlobClient.from_connection_string(
        conn_str=STORAGE_CONN_STR,
        container_name="markdowns",
        blob_name=output_blob_name,
    )
    output_blob.upload_blob(markdown_content, overwrite=True)

    output_json_blob_name = os.path.splitext(blob_name)[0] + ".json"
    output_json_blob = BlobClient.from_connection_string(
        conn_str=STORAGE_CONN_STR,
        container_name="markdowns",
        blob_name=output_json_blob_name,
    )
    output_json_blob.upload_blob(json_content, overwrite=True)

    print("Markdown and json uploaded:", output_blob_name)
    return True

def upload_final_images(images_folder: str, document_id: str) -> list[str]:
    """Upload all images in a folder to the image container under document_id/.

    Returns:
        list of uploaded image filenames (not full blob paths)
    """
    if not os.path.exists(images_folder):
        print(f"Final images folder not found: {images_folder}")
        return []

    image_files = sorted(
        [f for f in os.listdir(images_folder) if f.lower().endswith((".jpeg", ".jpg", ".png", ".gif", ".webp"))]
    )
    if not image_files:
        print(f"No images found in final images folder: {images_folder}")
        return []

    uploaded_names: list[str] = []
    print(f"Uploading {len(image_files)} image(s) from final folder")
    for filename in image_files:
        local_path = os.path.join(images_folder, filename)
        blob_name = document_id + "/" + filename
        try:
            image_blob = BlobClient.from_connection_string(
                conn_str=STORAGE_CONN_STR,
                container_name="images",
                blob_name=blob_name,
            )
            with open(local_path, "rb") as f:
                image_blob.upload_blob(f, overwrite=True)
            uploaded_names.append(filename)
        except Exception as e:
            print(f"Error uploading image {filename}: {e}")
            raise

    return uploaded_names


def upload_batch_pdf(document_id: str, batch_filename: str, batch_pdf_path: str) -> str:
    """Upload a batch PDF to blob storage.
    
    Args:
        document_id: The document ID
        batch_filename: Name of the batch file (e.g., batch_0001.pdf)
        batch_pdf_path: Local path to the batch PDF file
        
    Returns:
        The blob path where the PDF was uploaded
    """
    blob_name = f"{document_id}/batches/{batch_filename}"
    blob_client = BlobClient.from_connection_string(
        conn_str=STORAGE_CONN_STR,
        container_name="pdfs",
        blob_name=blob_name,
    )
    
    with open(batch_pdf_path, "rb") as f:
        blob_client.upload_blob(f, overwrite=True)
    
    print(f"Batch PDF uploaded: {blob_name}")
    return blob_name


def upload_batch_markdown(document_id: str, batch_name: str, markdown_content: str, json_content: str) -> bool:
    """Upload batch markdown and JSON to the markdown container.
    
    Args:
        document_id: The document ID
        batch_name: Name of the batch (e.g., batch_0001)
        markdown_content: The markdown content to upload
        json_content: The JSON metadata content to upload
        
    Returns:
        True if upload succeeded
    """
    # Upload markdown
    md_blob_name = f"{document_id}/batches/{batch_name}.md"
    md_blob = BlobClient.from_connection_string(
        conn_str=STORAGE_CONN_STR,
        container_name="markdowns",
        blob_name=md_blob_name,
    )
    md_blob.upload_blob(markdown_content, overwrite=True)
    
    # Upload JSON
    json_blob_name = f"{document_id}/batches/{batch_name}.json"
    json_blob = BlobClient.from_connection_string(
        conn_str=STORAGE_CONN_STR,
        container_name="markdowns",
        blob_name=json_blob_name,
    )
    json_blob.upload_blob(json_content, overwrite=True)
    
    print(f"Batch markdown uploaded: {md_blob_name}")
    return True


def download_batch_markdowns(document_id: str, batch_count: int) -> tuple[list[str], list[str]]:
    """Download all batch markdown and JSON files for a document.
    
    Args:
        document_id: The document ID
        batch_count: Number of batches to download
        
    Returns:
        Tuple of (markdown_contents, json_contents) lists
    """
    md_contents = []
    json_contents = []
    
    for i in range(1, batch_count + 1):
        batch_name = f"batch_{i:04d}"
        
        # Download MD
        md_blob_name = f"{document_id}/batches/{batch_name}.md"
        md_blob = BlobClient.from_connection_string(
            conn_str=STORAGE_CONN_STR,
            container_name="markdowns",
            blob_name=md_blob_name,
        )
        md_content = md_blob.download_blob().readall().decode("utf-8")
        md_contents.append(md_content)
        
        # Download JSON
        json_blob_name = f"{document_id}/batches/{batch_name}.json"
        json_blob = BlobClient.from_connection_string(
            conn_str=STORAGE_CONN_STR,
            container_name="markdowns",
            blob_name=json_blob_name,
        )
        json_content = json_blob.download_blob().readall().decode("utf-8")
        json_contents.append(json_content)
    
    return md_contents, json_contents


def list_images_in_container(document_id: str) -> list[str]:
    """List all image filenames in the image container for a given document_id.
    
    Args:
        document_id: The document ID
        
    Returns:
        List of image filenames (without the doc_id prefix path)
    """
    container_client = ContainerClient.from_connection_string(
        conn_str=STORAGE_CONN_STR,
        container_name="images",
    )
    
    prefix = f"{document_id}/"
    image_names: list[str] = []
    
    try:
        blobs = container_client.list_blobs(name_starts_with=prefix)
        for blob in blobs:
            # Extract just the filename from the full blob path
            filename = blob.name.removeprefix(prefix)
            if filename.lower().endswith((".jpeg", ".jpg", ".png")):
                image_names.append(filename)
    except Exception as e:
        print(f"Error listing images for document {document_id}: {e}")
    
    return sorted(image_names)


def _copy_dst_name(blob_name: str, src_prefix: str, dst_prefix: str) -> str:
    """Compute destination blob name: path under dst_prefix, with doc_id -> og_doc_id in filenames."""
    if not blob_name.startswith(f"{src_prefix}/"):
        return blob_name.replace(src_prefix, dst_prefix)
    # relative path under src_prefix (e.g. "doc_id.pdf" or "batches/batch_001.pdf")
    relative = blob_name[len(src_prefix) + 1 :]
    # rename doc_id.pdf -> og_doc_id.pdf, doc_id.md -> og_doc_id.md, doc_id.json -> og_doc_id.json
    if relative == f"{src_prefix}.pdf":
        relative = f"{dst_prefix}.pdf"
    elif relative == f"{src_prefix}.md":
        relative = f"{dst_prefix}.md"
    elif relative == f"{src_prefix}.json":
        relative = f"{dst_prefix}.json"
    else:
        # batches, images: only change prefix; replace doc_id in rest if present
        relative = relative.replace(src_prefix, dst_prefix)
    return f"{dst_prefix}/{relative}"


def copy_blobs(container_name: str, src_prefix: str, dst_prefix: str):
    """Copy all blobs under src_prefix/ to dst_prefix/ within the same container.
    Renames doc_id.pdf -> og_doc_id.pdf, doc_id.md -> og_doc_id.md, doc_id.json -> og_doc_id.json."""
    container_client = ContainerClient.from_connection_string(
        conn_str=STORAGE_CONN_STR,
        container_name=container_name,
    )
    blobs = list(container_client.list_blobs(name_starts_with=f"{src_prefix}/"))
    for blob in blobs:
        src_blob = BlobClient.from_connection_string(
            conn_str=STORAGE_CONN_STR,
            container_name=container_name,
            blob_name=blob.name,
        )
        new_name = _copy_dst_name(blob.name, src_prefix, dst_prefix)
        dst_blob = BlobClient.from_connection_string(
            conn_str=STORAGE_CONN_STR,
            container_name=container_name,
            blob_name=new_name,
        )
        dst_blob.start_copy_from_url(src_blob.url)
        print(f"Copied blob {blob.name} -> {new_name}")


def delete_blob_prefix(container_name: str, prefix: str):
    """Delete all blobs under prefix/ in a container."""
    container_client = ContainerClient.from_connection_string(
        conn_str=STORAGE_CONN_STR,
        container_name=container_name,
    )
    blobs = list(container_client.list_blobs(name_starts_with=f"{prefix}/"))
    for blob in blobs:
        container_client.delete_blob(blob.name)
        print(f"Deleted blob {container_name}/{blob.name}")