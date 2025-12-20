from fastapi import APIRouter, Depends, HTTPException
from services.userService import UserService
from data.dbClient import get_db
from sqlalchemy.orm import Session
from data.schemas.userSchema import User, GetUserResponse, UpdateUserRequest
from middleware import verify_access_token

user_router = APIRouter(prefix="/users", tags=["users"])


@user_router.get("/{user_id}", response_model=GetUserResponse)
def get_user_by_id(user_id: str, db: Session = Depends(get_db), user_id_from_token: str = Depends(verify_access_token)):
    user_service = UserService(db)
    print(user_id_from_token)
    user_response = user_service.get_user_by_id(user_id)
    if not user_response:
        raise HTTPException(status_code=404, detail="User not found")
    return user_response

@user_router.put("/{user_id}")
def update_user(user_id: str, user: UpdateUserRequest,db: Session = Depends(get_db)):
    user_service = UserService(db)
    return user_service.update_user(user_id, user)

@user_router.delete("/{user_id}")
def delete_user(user_id: str, db: Session = Depends(get_db)):
    user_service = UserService(db)
    return user_service.delete_user(user_id)
