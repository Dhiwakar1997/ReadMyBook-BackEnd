from fastapi import APIRouter, Depends, HTTPException, Request
from users.data.schema import (
    SignupRequest, SignupResponse, LoginRequest, LoginResponse, 
    RefreshTokenRequest, GoogleCallbackRequest, GoogleCallbackResponse, ForgetPasswordRequest, ResetPasswordRequest
)
from users.service.user_service import UserService, GoogleAuthService
from core.db_client import get_db
from sqlalchemy.orm import Session

auth_router = APIRouter(prefix="/auth", tags=["auth"])

@auth_router.post("/signup", response_model=SignupResponse)
def signup(request_model: SignupRequest, db: Session = Depends(get_db)):
    user_service = UserService(db)
    user = user_service.create_user(request_model)
    return SignupResponse(message="User created successfully", user_id=user.user_id)

@auth_router.post("/login", response_model=LoginResponse)
def login(request_model: LoginRequest, db: Session = Depends(get_db)):
    user_service = UserService(db)
    return user_service.login_user(request_model)

@auth_router.post("/refresh-token", response_model=LoginResponse)
def refresh_token(request: Request, request_model: RefreshTokenRequest, db: Session = Depends(get_db)):
    new_access_token = None
    user_id = None

    refresh_token = request_model.refresh_token
    user_service = UserService(db)

    access_token_tuple= user_service.get_new_access_token(refresh_token)
    if access_token_tuple is not None:
        new_access_token, user_id = access_token_tuple
    if new_access_token:
        return LoginResponse(access_token=new_access_token, refresh_token=refresh_token, user_id=user_id)
    else:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

@auth_router.get("/verify-email")
def verify_email(request: Request, db: Session = Depends(get_db)):
    verification_code = request.query_params.get("verification_code","")
    user_id = request.query_params.get("user_id","")
    user_service = UserService(db)
    user_service.verify_email(verification_code, user_id)
    return {"message": "Email verified successfully"}

@auth_router.post("/logout")
def logout():
    return {"message": "User logged out"}

@auth_router.post("/forget-password")
def forget_password_request(request: Request, request_model: ForgetPasswordRequest, db: Session = Depends(get_db)):
    email_id = request_model.email_id
    user_service = UserService(db)
    user_service.forget_password(email_id)
    return {"message": "Password reset initiated. Please check your email."}

@auth_router.post("/reset-password")
def reset_password(request: Request, request_model: ResetPasswordRequest, db: Session = Depends(get_db)):
    email_id = request_model.email_id
    reset_code = request_model.reset_code
    new_password = request_model.new_password
    user_service = UserService(db)
    user_service.reset_password(email_id, reset_code, new_password)
    return {"message": "Password has been reset successfully."}

@auth_router.post("/google/callback", response_model=GoogleCallbackResponse)
def google_oauth_callback(
    request_model: GoogleCallbackRequest,
    db: Session = Depends(get_db)
):
    try:
        google_auth_service = GoogleAuthService()
        google_user_info = google_auth_service.verify_id_token(request_model.id_token)
        
        user_service = UserService(db)
        login_response = user_service.handle_google_oauth(google_user_info)
        
        return GoogleCallbackResponse(
            access_token=login_response.access_token,
            refresh_token=login_response.refresh_token,
            user_id=login_response.user_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error during Google OAuth: {str(e)}"
        )
