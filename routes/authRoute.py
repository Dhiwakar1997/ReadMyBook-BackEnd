from fastapi import APIRouter, Depends, HTTPException, Request
from data.schemas.authSchema import (
    SignupRequest, SignupResponse, LoginRequest, LoginResponse, 
    RefreshTokenRequest, GoogleCallbackRequest, GoogleCallbackResponse
)
from services.userService import UserService
from services.googleAuthService import GoogleAuthService
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

@auth_router.get("/verify-email")
def verify_email(request: Request, db: Session = Depends(get_db)):
    verification_code = request.query_params.get("verification_code")
    user_id = request.query_params.get("user_id")
    user_service = UserService(db)
    user_service.verify_email(verification_code, user_id)
    return {"message": "Email verified successfully"}

@auth_router.post("/logout")
def logout():
    return {"message": "User logged out"}

@auth_router.post("/google/callback", response_model=GoogleCallbackResponse)
def google_oauth_callback(
    request_model: GoogleCallbackRequest,
    db: Session = Depends(get_db)
):
    """
    Google OAuth callback endpoint.
    
    This endpoint:
    1. Receives a Google ID token from the Flutter Android app
    2. Verifies the token's signature, expiration, and audience
    3. Validates that the email is verified
    4. Creates a new user if they don't exist, or logs in existing user
    5. Issues first-party JWT tokens (access_token and refresh_token)
    
    Args:
        request_model: Contains the Google ID token
        
    Returns:
        GoogleCallbackResponse with access_token, refresh_token, and user_id
        
    Raises:
        HTTPException:
            - 401 if token is invalid, expired, or has wrong audience
            - 403 if email is not verified
            - 409 if user exists with same email but different auth provider
            - 500 for unexpected errors
    """
    try:
        # Initialize Google Auth Service
        google_auth_service = GoogleAuthService()
        
        # Verify the Google ID token and extract user information
        google_user_info = google_auth_service.verify_id_token(request_model.id_token)
        
        # Handle user login/registration
        user_service = UserService(db)
        login_response = user_service.handle_google_oauth(google_user_info)
        
        # Return response with first-party JWT tokens
        return GoogleCallbackResponse(
            access_token=login_response.access_token,
            refresh_token=login_response.refresh_token,
            user_id=login_response.user_id
        )
        
    except HTTPException:
        # Re-raise HTTPExceptions (they already have proper status codes)
        raise
    except Exception as e:
        # Catch any unexpected errors
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error during Google OAuth: {str(e)}"
        )
