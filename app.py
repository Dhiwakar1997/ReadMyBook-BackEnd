from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pathlib import Path
from core.db_client import Base, _api_engine
from sqlalchemy import text
from users.route import auth_router, user_router
from documents.route import document_router, markdown_router, pdf_router, image_router

from users.data.model import User
from documents.data.model import Document, DocumentAccessModel, DocumentBatch
from bookmarks.data.model import Bookmark

Base.metadata.create_all(bind=_api_engine)

app = FastAPI()

# Mount static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(auth_router)
app.include_router(user_router)
app.include_router(document_router)
app.include_router(image_router)
app.include_router(markdown_router)
app.include_router(pdf_router)

@app.get("/", response_class=HTMLResponse)
def read_root():
    """Serve the landing page"""
    html_path = Path(__file__).parent / "static" / "index.html"
    return html_path.read_text()

@app.get("/health")
def health_check():
    """Health check endpoint for monitoring"""
    return {"status": "healthy"}
