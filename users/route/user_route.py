from fastapi import APIRouter, Depends, HTTPException, Request
from users.data.schema import User, GetUserResponse, UpdateUserRequest, UserSearchResponse, UpdateBioRequest
from users.service.user_service import UserService
from core.db_client import get_db
from sqlalchemy.orm import Session
from middleware import verify_access_token, user_verfication

user_router = APIRouter(prefix="/users", tags=["users"])

@user_router.get("/search", response_model=UserSearchResponse, dependencies=[Depends(verify_access_token)])
def search_users(q: str, request: Request, db: Session = Depends(get_db)):
    user_service = UserService(db)
    results = user_service.search_users(q, request.state.user_id)
    return UserSearchResponse(results=results)

@user_router.get("/{user_id}", response_model=GetUserResponse)
def get_user_by_id(user_id: str, 
                   db: Session = Depends(get_db), 
                   user_id_from_token: str = Depends(user_verfication)):
    user_service = UserService(db)
    user_response = user_service.get_user_by_id(user_id)
    if not user_response:
        raise HTTPException(status_code=404, detail="User not found")
    return user_response

@user_router.put("/{user_id}",dependencies=[Depends(user_verfication)])
def update_user(user_id: str, user: UpdateUserRequest, db: Session = Depends(get_db)):
    user_service = UserService(db)
    return user_service.update_user(user_id, user)

@user_router.delete("/{user_id}",dependencies=[Depends(user_verfication)])
def delete_user(user_id: str, db: Session = Depends(get_db)):
    user_service = UserService(db)
    deleted_user = user_service.delete_user(user_id)
    if not deleted_user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "User deleted successfully", "user_id": user_id}

@user_router.patch("/{user_id}/bio", dependencies=[Depends(user_verfication)])
def update_bio(user_id: str, payload: UpdateBioRequest, db: Session = Depends(get_db)):
    user_service = UserService(db)
    user_service.update_bio(user_id, payload.bio)
    return {"message": "Bio updated", "user_id": user_id, "success": True, "status_code": 200}
