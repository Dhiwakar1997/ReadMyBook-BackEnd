from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pathlib import Path
from data.dbClient import Base, engine
from sqlalchemy import text
from routes.authRoute import auth_router
from routes.userRoute import user_router
from routes.documentRoute import document_router
from routes.imageRoute import image_router
from routes.audioRoute import audio_router
from routes.markdownRoute import markdown_router
from routes.pdfRoute import pdf_router

from data.models.usersModel import User
from data.models.documentsModel import Document
from data.models.documentAccessModel import DocumentAccessModel
from data.models.bookmarkModel import Bookmark
from data.models.documentBatchModel import DocumentBatch

Base.metadata.create_all(bind=engine)

app = FastAPI()

# Mount static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(auth_router)
app.include_router(user_router)
app.include_router(document_router)
app.include_router(image_router)
app.include_router(audio_router)
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
