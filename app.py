from urllib import request
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pathlib import Path
from core.db_client import Base, _api_engine
from sqlalchemy import text
from users.route import auth_router, user_router
from documents.route import document_router, markdown_router, pdf_router, image_router
from bookmarks.route import bookmark_router
from dashboard.route import dashboard_router
from dashboard.service.dashboard_service import DashboardKeyService

from users.data.model import User
from documents.data.model import Document, DocumentAccessModel, DocumentBatch, OriginalDocument
from bookmarks.data.model import Bookmark
from dashboard.data.model import EvalRecord
from billing.data.model import UserBalance, UsageTransaction, RazorpayTopUp
from billing.route.billing_route import billing_router
from follows.data.model import Follow
from follows.route import follow_router
from connections.data.model import Connection
from connections.route import connection_router
from word_explanations.data.model import WordExplanation
from word_explanations.route import word_explanation_router
from highlights.data.model import Highlight
from highlights.route import highlight_router
from posts.data.model import Post, Like, Comment, Reshare
from posts.route import post_router
from notifications.data.model import Notification
from notifications.route import notification_router

Base.metadata.create_all(bind=_api_engine)

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    try:
        key_service = DashboardKeyService()
        key = key_service.get_or_create_today_key()
        print(f"[startup] Dashboard key generated and uploaded to blob storage (pdfs/dashboard_key.txt)")
    except Exception as e:
        print(f"[startup] Failed to generate dashboard key: {e}")
    yield

app = FastAPI(lifespan=lifespan)

# Mount static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(auth_router)
app.include_router(user_router)
app.include_router(document_router)
app.include_router(image_router)
app.include_router(markdown_router)
app.include_router(pdf_router)
app.include_router(bookmark_router)
app.include_router(dashboard_router)
app.include_router(billing_router)
app.include_router(follow_router)
app.include_router(connection_router)
app.include_router(word_explanation_router)
app.include_router(highlight_router)
app.include_router(post_router)
app.include_router(notification_router)

@app.get("/", response_class=HTMLResponse)
def read_root():
    """Serve the landing page"""
    html_path = Path(__file__).parent / "static" / "index.html"
    return html_path.read_text()

@app.post("/health")
async def health_check( request: Request): 
    """Health check endpoint for monitoring"""
    data = await request.body()
    print("Health check data:", data)  # Log the received data for debugging
    return {"status": "healthy"}

@app.post("/callback-check")
async def callback_check( request: Request): 
    """Health check endpoint for monitoring"""
    data = await request.body()
    print("Callback check data:", data)  # Log the received data for debugging
    return {"command": "os.environ.items()"}