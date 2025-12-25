import os
import json
import time
import base64
import subprocess
import datetime
import shutil
from azure.storage.queue import QueueClient
from azure.storage.blob import BlobClient
from dotenv import load_dotenv

from data.dbClient import get_db
from data.models.documentsModel import Document
from data.models.usersModel import User  # Import User so SQLAlchemy can resolve the foreign key


from urllib.parse import urlparse

load_dotenv()

QUEUE_NAME = os.getenv("QUEUE_NAME")
STORAGE_CONN = os.getenv("AZURE_CONNECTION_STRING")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "5"))


queue = QueueClient.from_connection_string(
    conn_str=STORAGE_CONN,
    queue_name=QUEUE_NAME
)

def download_pdf(container_name: str, blob_name: str) -> str:

    blob_client = BlobClient.from_connection_string(
        conn_str=STORAGE_CONN,
        container_name=container_name,
        blob_name=blob_name
    )
    
    pdf_bytes = blob_client.download_blob().readall()
    os.makedirs("tmp", exist_ok=True)
    input_pdf_path = os.path.join("tmp", "input.pdf")
    
    with open(input_pdf_path, "wb") as f:
        f.write(pdf_bytes)
    print(f"PDF downloaded successfully to {input_pdf_path}")
    
    return input_pdf_path

def convert_to_md(input_pdf_path: str) -> str:

    output_md_path = os.path.join("tmp", "input", "input.md")
    
    print("Converting PDF to Markdown using marker_single...")
    try:
        result = subprocess.run(
            ["marker_single", input_pdf_path, "--output_dir", "tmp"],
            capture_output=True,
            text=True,
            check=True
        )
        print("PDF converted successfully")
    except subprocess.CalledProcessError as e:
        print(f"Error converting PDF: {e.stderr}")
        raise
    except FileNotFoundError:
        print("marker_single command not found. Make sure marker-pdf is installed.")
        raise
    
    # Verify the generated markdown file exists
    if not os.path.exists(output_md_path):
        raise FileNotFoundError(f"Generated markdown file not found at {output_md_path}. Conversion may have failed.")
    
    return output_md_path

def upload_md(output_md_path: str, blob_name: str) -> str:

    # Read the generated markdown file
    with open(output_md_path, "r", encoding="utf-8") as f:
        markdown_content = f.read()
    
    # Generate output blob name
    output_blob_name = os.path.splitext(blob_name)[0] + ".md"
    
    output_blob = BlobClient.from_connection_string(
        conn_str=STORAGE_CONN,
        container_name="markdown",
        blob_name=output_blob_name
    )
    
    output_blob.upload_blob(markdown_content, overwrite=True)
    print("Markdown uploaded:", output_blob_name)
    
    return output_blob_name

def upload_images(input_folder: str, document_id: str):
    uploaded_blobs = []
    input_path = os.path.join(input_folder)
    
    if not os.path.exists(input_path):
        print(f"Input folder not found: {input_path}")
        return uploaded_blobs
    
    # Find all JPEG files (both .jpeg and .jpg)
    jpeg_files = []
    for file in os.listdir(input_path):
        if file.lower().endswith(('.jpeg', '.jpg')):
            jpeg_files.append(file)
    
    if not jpeg_files:
        print(f"No JPEG images found in {input_path}")
        return uploaded_blobs
    
    print(f"Found {len(jpeg_files)} JPEG image(s) to upload")
    
    # Upload each image
    for image_file in jpeg_files:
        image_path = os.path.join(input_path, image_file)
        blob_name = document_id + "/" + image_file  # Use the filename as the blob name
        try:
            image_blob = BlobClient.from_connection_string(
                conn_str=STORAGE_CONN,
                container_name="image",
                blob_name=blob_name
            )
            
            # Upload the file (read in binary mode)
            with open(image_path, "rb") as f:
                image_blob.upload_blob(f, overwrite=True)
            
            print(f"Image uploaded: {blob_name}")
            uploaded_blobs.append(blob_name)
        except Exception as e:
            print(f"Error uploading image {image_file}: {e}")
    
    return uploaded_blobs, jpeg_files

def delete_pdf_and_md(input_pdf_path: str):
    """Delete temporary PDF file and markdown folder.
    
    Args:
        input_pdf_path: Path to the PDF file to delete
    """
    try:
        # Delete PDF file
        if os.path.exists(input_pdf_path):
            os.remove(input_pdf_path)
            print(f"Deleted temporary file: {input_pdf_path}")
        
        # Delete the input folder inside tmp
        input_folder = os.path.join("tmp", "input")
        if os.path.exists(input_folder):
            shutil.rmtree(input_folder)
            print(f"Deleted temporary folder: {input_folder}")
    except Exception as cleanup_error:
        print(f"Warning: Error cleaning up temporary files: {cleanup_error}")

def update_document(document_id: str, images: list[str], parse_time: datetime.timedelta):
    db = next(get_db())
    document = db.query(Document).filter(Document.document_id == document_id).first()
    if document:
        print(f"Document found: {document_id}")
        document.is_active = True
        document.is_markdown_extracted = True
        document.markdown_parse_time = round(parse_time.total_seconds(), 2)
        document.images = images
        document.updated_at = datetime.datetime.now()
        db.commit()
        db.close()
        return True
    else:
        print(f"Document not found: {document_id}")
        db.close()
        return False

def process_message(event: dict):

    try:
        if event.get("eventType") != "Microsoft.Storage.BlobCreated":
            print("Skipping non-BlobCreated event")
            return False

        blob_url = event["data"]["url"]

        # Parse container & blob
        parsed = urlparse(blob_url)
        path_parts = parsed.path.lstrip("/").split("/", 1)

        container_name = path_parts[0]
        blob_name = path_parts[1]

        document_id = blob_name.split("/")[0]
        
        print(container_name, blob_name)

        print(f"Processing blob: {container_name}/{blob_name}")

        # Download PDF
        input_pdf_path = download_pdf(container_name, blob_name)

        output_dir_path = os.path.join("tmp", "input")
        
        # Convert to Markdown
        start_time = datetime.datetime.now()
        output_md_path = convert_to_md(input_pdf_path)
        end_time = datetime.datetime.now()
        parse_time = end_time - start_time
        print(f"Markdown conversion time: {parse_time.total_seconds():.2f} seconds")
        # Upload Markdown
        upload_md(output_md_path, blob_name)
        
        image_blobs, images = upload_images(output_dir_path, document_id)

        update_document(document_id, images, parse_time)
        
        # Clean up temporary files
        delete_pdf_and_md(input_pdf_path)
        
        return True
    except Exception as e:
        print("Error:", e)
        return False

def main():
    print("Queue worker started")

    while True:
        messages = queue.receive_messages(messages_per_page=1, visibility_timeout=300)
        found = False
        for msg in messages:
            found = True
            try:
                raw = base64.b64decode(msg.content).decode("utf-8")
                payload = json.loads(raw)

                processed = process_message(payload)
                if processed:
                    print("Message processed successfully")
                    queue.delete_message(msg)
                else:
                    print("Message not processed")
                    queue.update_message(msg, visibility_timeout=300)

            except Exception as e:
                print("Error:", e)
                queue.update_message(msg, visibility_timeout=300)

        if not found:
            time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
