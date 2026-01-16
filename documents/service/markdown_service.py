import os
from azure.storage.blob import (
    BlobServiceClient,
    generate_blob_sas,
    BlobSasPermissions
)
import datetime
from datetime import timedelta

blob_service_client = BlobServiceClient.from_connection_string(conn_str=os.getenv("AZURE_CONNECTION_STRING", ""))

class MarkdownService:
    
    def __init__(self):
        self.blob_service_client = blob_service_client
        self.container_name = "markdowns"
    
    def get_markdown_download_url(self, document_id: str, expiry_minutes: int = 60) -> str:
        """Generate a temporary download URL for a markdown file."""
        blob_name = f"{document_id}/{document_id}.md"
        
        account_name = self.blob_service_client.account_name
        credential = self.blob_service_client.credential.account_key
        
        sas_token = generate_blob_sas(
            account_name=account_name,
            container_name=self.container_name,
            blob_name=blob_name,
            account_key=credential,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.datetime.utcnow() + timedelta(minutes=expiry_minutes)
        )
        
        download_url = (
            f"https://{account_name}.blob.core.windows.net/"
            f"{self.container_name}/{blob_name}?{sas_token}"
        )
        
        return download_url
    
    def get_json_download_url(self, document_id: str, expiry_minutes: int = 60) -> str:
        """Generate a temporary download URL for a json file."""
        blob_name = f"{document_id}/{document_id}.json"
        account_name = self.blob_service_client.account_name
        credential = self.blob_service_client.credential.account_key
        
        sas_token = generate_blob_sas(
            account_name=account_name,
            container_name=self.container_name,
            blob_name=blob_name,
            account_key=credential,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.datetime.utcnow() + timedelta(minutes=expiry_minutes)
        )

        download_url = (
            f"https://{account_name}.blob.core.windows.net/"
            f"{self.container_name}/{blob_name}?{sas_token}"
        )
        
        return download_url
