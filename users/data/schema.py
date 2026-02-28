from pydantic import BaseModel
from enum import Enum
from typing import Optional

class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"

class User(BaseModel):
    user_id: str
    first_name: str
    last_name: str
    date_of_birth: str
    gender: Gender
    email_id: str
    is_verified: bool

    class config:
        from_attributes = True

class GetUserResponse(BaseModel):
    user_id: str
    first_name: str
    last_name: str
    date_of_birth: str
    gender: Gender
    email_id: str
    created_at: str
    updated_at: str
    deleted_at: str = None
    is_deleted: bool
    is_active: bool
    is_verified: bool
    is_private: bool = False
    
    class config:
        from_attributes = True

class UpdateUserRequest(BaseModel):
    first_name: str
    last_name: str
    date_of_birth: str
    gender: Gender

# Auth schemas
class SignupRequest(BaseModel):
    email_id: str
    password: str
    first_name: str
    last_name: str = None
    date_of_birth: str = None
    gender: Gender = None

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

class ForgetPasswordRequest(BaseModel):
    email_id: str

class ResetPasswordRequest(BaseModel):
    email_id: str
    reset_code: str
    new_password: str

class GoogleCallbackRequest(BaseModel):
    """Request model for Google OAuth callback endpoint."""
    id_token: str

class GoogleCallbackResponse(BaseModel):
    """Response model for Google OAuth callback endpoint."""
    access_token: str
    refresh_token: str
    user_id: str

class UserSearchResult(BaseModel):
    user_id: str
    first_name: str
    last_name: str = None
    mutual_followers: int
    mutual_following: int
    is_following: bool = False

class UserSearchResponse(BaseModel):
    results: list[UserSearchResult]


class UpdateBioRequest(BaseModel):
    bio: Optional[str] = None
