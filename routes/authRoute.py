from fastapi import APIRouter, Depends, HTTPException, Request
from data.schemas.authSchema import SignupRequest, SignupResponse,LoginRequest,LoginResponse, RefreshTokenRequest
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

@auth_router.post("/refresh-token",response_model=LoginResponse)
def refresh_token(request: Request, request_model: RefreshTokenRequest, db: Session = Depends(get_db)):
    refresh_token = request_model.refresh_token
    user_service = UserService(db)
    new_access_token, user_id = user_service.get_new_access_token(refresh_token)
    if new_access_token:
        return LoginResponse(access_token=new_access_token, refresh_token=refresh_token,user_id=user_id)
    else:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

@auth_router.post("/verify-email")
def verify_email(request: Request, db: Session = Depends(get_db)):
    verification_code = request.query_params.get("verification_code")
    user_id = request.query_params.get("user_id")
    user_service = UserService(db)
    return user_service.verify_email(verification_code, user_id)

@auth_router.post("/logout")
def logout():
    return {"message": "User logged out"}
