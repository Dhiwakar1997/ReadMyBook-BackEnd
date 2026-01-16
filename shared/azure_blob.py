import os
from azure.storage.blob import (
    BlobServiceClient,
    generate_blob_sas,
    BlobSasPermissions
)
import datetime
from datetime import timedelta

blob_service_client = BlobServiceClient.from_connection_string(conn_str=os.getenv("AZURE_CONNECTION_STRING"))

class AzureBlobService:

    def __init__(self):
        self.blob_service_client = blob_service_client


    def generate_upload_url(self, container_name="pdfs", file_name: str = ""):

        account_name = self.blob_service_client.account_name
        credential = self.blob_service_client.credential.account_key

        sas_token = generate_blob_sas(
            account_name=account_name,
            container_name=container_name,
            blob_name=file_name,
            account_key=credential,
            permission=BlobSasPermissions(write=True, create=True),
            expiry=datetime.datetime.utcnow() + timedelta(minutes=15)
        )

        upload_url = (
            f"https://{account_name}.blob.core.windows.net/"
            f"{container_name}/{file_name}?{sas_token}"
        )

        return upload_url
