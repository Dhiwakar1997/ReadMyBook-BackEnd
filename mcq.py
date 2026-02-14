from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn

@asynccontextmanager
async def lifespan(app):
    print("Startup")
    yield
    print("Shutdown")

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def root():
    return {"message": "Hello World"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)