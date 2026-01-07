"""
One-time script to create the document_batches table.
Run with: python create_document_batches_table.py
"""
import os
from dotenv import load_dotenv

env_file = os.getenv("ENV_FILE", ".env.dev")
load_dotenv(env_file)

from data.dbClient import engine, Base
# Import Document first to register it with Base.metadata
from data.models.documentsModel import Document
from data.models.documentBatchModel import DocumentBatch

# Create the table
Base.metadata.create_all(bind=engine, tables=[DocumentBatch.__table__])

print("document_batches table created successfully!")
