from pydantic import BaseModel
from data.schemas.userSchema import Gender

class SignupRequest(BaseModel):
    email: str
    password: str
    first_name: str
    last_name: str=None
    date_of_birth: str=None
    gender: Gender=None

class SignupResponse(BaseModel):
    message: str

class LoginRequest(BaseModel):
    email: str
    password: str

class LoginResponse(BaseModel):
    jwt_token: str
    expires_in: int
    user_id: str