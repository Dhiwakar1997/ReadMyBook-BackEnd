from pydantic import BaseModel
from enum import Enum

class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"

class User(BaseModel):
    user_id: str
    first_name: str
    last_name: str
    date_of_birth: str
    gender: str
    email: str
    password: str

class GetUserResponse(BaseModel):
    class Config:
        from_attributes = True
    user: User

class UpdateUserRequest(BaseModel):
    user: User
