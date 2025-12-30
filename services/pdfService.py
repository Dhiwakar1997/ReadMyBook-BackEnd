from fastapi import HTTPException
from services.azureBlobService import AzureBlobService
from azure.storage.blob import (
    BlobServiceClient,
    generate_blob_sas,
    BlobSasPermissions
)
import os
import datetime
from datetime import timedelta


class PdfService:
    def __init__(self):
        self.azure_blob_service = AzureBlobService()
        self.blob_service_client = self.azure_blob_service.blob_service_client
        self.container_name = "pdf"

    def get_pdf_download_url(self, document_id: str, expiry_minutes: int = 60) -> str:
        """Generate a temporary download URL for a PDF file.
        
        Args:
            document_id: The document ID
            expiry_minutes: Number of minutes until the URL expires (default: 60)
        
        Returns:
            Temporary download URL with SAS token
        """
        # Construct the blob path: document_id/document_id.pdf
        blob_name = f"{document_id}/{document_id}.pdf"
        
        account_name = self.blob_service_client.account_name
        credential = self.blob_service_client.credential.account_key
        
        # Generate SAS token with read permission
        sas_token = generate_blob_sas(
            account_name=account_name,
            container_name=self.container_name,
            blob_name=blob_name,
            account_key=credential,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.datetime.utcnow() + timedelta(minutes=expiry_minutes)
        )
        
        # Construct the download URL
        download_url = (
            f"https://{account_name}.blob.core.windows.net/"
            f"{self.container_name}/{blob_name}?{sas_token}"
        )
        
        return download_url