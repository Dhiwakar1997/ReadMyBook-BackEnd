from fastapi import APIRouter

auth_router = APIRouter(prefix="/auth", tags=["auth"])

@auth_router.post("/signup")
def signup():
    return {"message": "User signed up"}

@auth_router.post("/login")
def login():
    return {"message": "User logged in"}

@auth_router.post("/logout")
def logout():
    return {"message": "User logged out"}
