from fastapi import FastAPI
from data.dbClient import Base, engine
from routes.authRoute import auth_router
from routes.userRoute import user_router
from routes.documentRoute import document_router
from routes.imageRoute import image_router
from routes.audioRoute import audio_router
from routes.markdownRoute import markdown_router
import uvicorn


app = FastAPI()

app.include_router(auth_router)
app.include_router(user_router)
app.include_router(document_router)
app.include_router(image_router)
app.include_router(audio_router)
app.include_router(markdown_router)

@app.get("/")
def read_root():
    return {"message": "Hello, World!"}

