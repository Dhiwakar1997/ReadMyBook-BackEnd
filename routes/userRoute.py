from fastapi import APIRouter
from data.schemas import BaseResponse
from data.schemas.userSchema import GetUserResponse, UpdateUserRequest

user_router = APIRouter(prefix="/users", tags=["users"])

@user_router.get("/{user_id}")
def get_user_by_id(user_id: str, response_model:GetUserResponse):
    return {'message':"User get"}

@user_router.put("/{user_id}")
def update_user(user_id: str):
    return {"message": "User updated"}

@user_router.delete("/{user_id}")
def delete_user(user_id: str):
    return {"message": "User deleted"}
