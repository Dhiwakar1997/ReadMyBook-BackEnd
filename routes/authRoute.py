from fastapi import APIRouter, Depends
from data.schemas.authSchema import SignupRequest, SignupResponse,LoginRequest,LoginResponse
from services.userService import UserService
from data.dbClient import get_db
from sqlalchemy.orm import Session

auth_router = APIRouter(prefix="/auth", tags=["auth"])

@auth_router.post("/signup",response_model=SignupResponse)
def signup(request_model: SignupRequest, db: Session = Depends(get_db)):
    user_service = UserService(db)
    user = user_service.create_user(request_model)
    return SignupResponse(message="User created successfully", user_id=user.user_id)

@auth_router.post("/login",response_model=LoginResponse)
def login(request_model: LoginRequest, db: Session = Depends(get_db)):
    user_service = UserService(db)
    return user_service.login_user(request_model)

@auth_router.post("/logout")
def logout():
    return {"message": "User logged out"}
