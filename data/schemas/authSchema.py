from pydantic import BaseModel
from data.schemas.userSchema import Gender

class SignupRequest(BaseModel):
    email_id: str
    password: str
    first_name: str
    last_name: str=None
    date_of_birth: str=None
    gender: Gender=None

class SignupResponse(BaseModel):
    message: str
    user_id: str

class LoginRequest(BaseModel):
    email_id: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    user_id: str

class RefreshTokenRequest(BaseModel):
    refresh_token: str

class GoogleCallbackRequest(BaseModel):
    """Request model for Google OAuth callback endpoint."""
    id_token: str

class GoogleCallbackResponse(BaseModel):
    """Response model for Google OAuth callback endpoint."""
    access_token: str
    refresh_token: str
    user_id: str
