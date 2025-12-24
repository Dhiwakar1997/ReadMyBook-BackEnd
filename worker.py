import os
import json
import time
import base64
import subprocess
import shutil
from azure.storage.queue import QueueClient
from azure.storage.blob import BlobClient
from dotenv import load_dotenv

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
        print(container_name, blob_name)

        print(f"Processing blob: {container_name}/{blob_name}")

        # Download PDF
        input_pdf_path = download_pdf(container_name, blob_name)
        
        # Convert to Markdown
        output_md_path = convert_to_md(input_pdf_path)
        
        # Upload Markdown
        upload_md(output_md_path, blob_name)
        
        # Clean up temporary files
        delete_pdf_and_md(input_pdf_path)
        
        return True
    except Exception as e:
        print("Error:", e)
        return False

def main():
    print("Queue worker started")

    while True:
        messages = queue.receive_messages(messages_per_page=1, visibility_timeout=3000)
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
                    queue.update_message(msg, visibility_timeout=3000)

            except Exception as e:
                print("Error:", e)
                queue.update_message(msg, visibility_timeout=3000)

        if not found:
            time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
