from fastapi import APIRouter

audio_router = APIRouter()

@audio_router.get("/audios")
def get_audios():
    return {"message": "Hello, World!"}