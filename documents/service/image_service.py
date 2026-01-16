import os
from azure.storage.blob import (
    BlobServiceClient,
    generate_blob_sas,
    BlobSasPermissions
)
import datetime
from datetime import timedelta
from typing import Dict, List

blob_service_client = BlobServiceClient.from_connection_string(conn_str=os.getenv("AZURE_CONNECTION_STRING"))

class ImageService:
    
    def __init__(self):
        self.blob_service_client = blob_service_client
        self.container_name = "images"
    
    def get_image_download_url(self, document_id: str, image_name: str, expiry_minutes: int = 60) -> str:
        """Generate a temporary download URL for a single image."""
        blob_name = f"{document_id}/{image_name}"
        
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
    
    def get_images_download_urls(self, document_id: str, image_names: List[str], expiry_minutes: int = 60) -> Dict[str, str]:
        """Generate temporary download URLs for multiple images."""
        if not image_names:
            return {}
        
        image_urls = {}
        account_name = self.blob_service_client.account_name
        credential = self.blob_service_client.credential.account_key
        expiry_time = datetime.datetime.utcnow() + timedelta(minutes=expiry_minutes)
        
        for image_name in image_names:
            blob_name = f"{document_id}/{image_name}"
            
            sas_token = generate_blob_sas(
                account_name=account_name,
                container_name=self.container_name,
                blob_name=blob_name,
                account_key=credential,
                permission=BlobSasPermissions(read=True),
                expiry=expiry_time
            )
            
            download_url = (
                f"https://{account_name}.blob.core.windows.net/"
                f"{self.container_name}/{blob_name}?{sas_token}"
            )
            
            image_urls[image_name] = download_url
        
        return image_urls
