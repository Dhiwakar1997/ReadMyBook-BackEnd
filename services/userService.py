import ulid
from data.repositories.userRepository import UserRepository
from data.models.usersModel import User
from data.schemas.authSchema import SignupRequest, LoginRequest, LoginResponse
from data.schemas.userSchema import GetUserResponse, UpdateUserRequest
from services.emailService import EmailService
from sqlalchemy.orm import Session
from jose import jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta

import os
import hashlib

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class UserService:

    def __init__(self, db: Session):
        self.user_repository = UserRepository(db)
        self.email_service = EmailService()

    def get_user_by_id(self, user_id: str):
        user=self.user_repository.get_user_by_id(user_id)
        if not user:
            return None

        user_response = GetUserResponse(user_id=user.user_id,
                        first_name=user.first_name,
                        last_name=user.last_name,
                        date_of_birth=user.date_of_birth.isoformat(),
                        gender=user.gender,
                        email_id=user.email_id,
                        created_at=user.created_at.isoformat(),
                        updated_at=user.updated_at.isoformat(),
                        deleted_at=user.deleted_at.isoformat() if user.deleted_at else "",
                        is_deleted=user.is_deleted,
                        is_active=user.is_active)
        return user_response

    def update_user(self, user_id: str, user_req: UpdateUserRequest):
        user = self.user_repository.get_user_by_id(user_id)
        if not user:
            return None
        user.first_name = user_req.first_name
        user.last_name = user_req.last_name
        user.date_of_birth = user_req.date_of_birth
        user.gender = user_req.gender
        user.updated_at = datetime.now()
        return self.user_repository.update_user(user_id, user)

    def delete_user(self, user_id: str):
        return self.user_repository.delete_user(user_id)

    def create_user(self, signup_request: SignupRequest):

        verification_code = self.generate_verification_code()
        verification_code_expires_at = datetime.now() + timedelta(hours=1)

        user = User(
            email_id=signup_request.email_id,
            first_name=signup_request.first_name,
            last_name=signup_request.last_name,
            date_of_birth=signup_request.date_of_birth,
            gender=signup_request.gender,
            verification_code=verification_code,
            verification_code_expires_at=verification_code_expires_at
        )
        user.user_id = "user_"+str(ulid.new())
        user.password = self.hash_password(signup_request.password)
        created_user = self.user_repository.create_user(user)
        #self.send_varification_email(created_user)
        return created_user

    def login_user(self, login_request: LoginRequest):
        user = self.user_repository.get_user_by_email_id(login_request.email_id)
        if not user:
            return None
        if not self.verify_password(login_request.password, user.password):
            return None

        access_token, refresh_token = self.generate_tokens(user.user_id)
        
        return LoginResponse(access_token=access_token, refresh_token=refresh_token, user_id=user.user_id)
        
    def generate_tokens(self, user_id: str):
        access_token = self.create_access_token(user_id)
        refresh_token = self.create_refresh_token(user_id)
        return access_token, refresh_token

    def hash_password(self,password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()

    def verify_password(self, plain: str, hashed: str) -> bool:
        return hashlib.sha256(plain.encode()).hexdigest() == hashed

    def create_access_token(self, user_id: str):
        payload = {
            "sub": user_id,
            "type": "access",
            "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        }
        return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

    
    def create_refresh_token(self, user_id: str):
        payload = {
            "sub": user_id,
            "type": "refresh",
            "exp": datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        }
        return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

    def get_new_access_token(self, refresh_token: str):
        try:
            payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
            if payload["type"] != "refresh":
                return None
            user_id = payload["sub"]

            new_access_token = self.create_access_token(user_id)
            return new_access_token, user_id
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None

    def send_varification_email(self, user: User):
        self.email_service.send_verification_email(user.email_id, user.verification_code)

    def generate_verification_code(self):
        return str(ulid.new())

    def verify_email(self, verification_code: str, user_id: str):
        user = self.user_repository.get_user_by_id(user_id)
        if not user:
            return None
        if user.verification_code != verification_code:
            return None
        if user.verification_code_expires_at < datetime.now():
            return None
        user.is_verified = True
        user.updated_at = datetime.now()
        user.verification_code = None
        user.verification_code_expires_at = None
        updated_user = self.user_repository.update_user(user_id, user)
        self.email_service.send_verification_success_email( user.email_id)
        return True