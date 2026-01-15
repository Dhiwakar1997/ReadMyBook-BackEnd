import ulid
from users.data.repository import UserRepository
from users.data.model import User
from users.data.schema import SignupRequest, LoginRequest, LoginResponse, GetUserResponse, UpdateUserRequest
from sqlalchemy.orm import Session
from jose import jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta

import os
import hashlib
import threading
import smtplib
from email.message import EmailMessage
from fastapi import HTTPException

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class EmailService:
    def __init__(self):
        self.domain_endpoint ="http://localhost:8080"
        self.smtp_server = "smtp.gmail.com"
        self.smtp_port = 587
        self.smtp_username = os.getenv("SMTP_USERNAME")
        self.smtp_password = os.getenv("SMTP_PASSWORD")

    def send_verification_email(self, email_id: str, verification_code: str, user_id: str):
        msg = EmailMessage()
        link = f"{self.domain_endpoint}/auth/verify-email?verification_code={verification_code}&user_id={user_id}"
        msg.set_content(
            f"Dear User,\n\n"
            "Thank you for registering with ReadMyBook.\n"
            f"To complete your registration, please verify your email address by clicking the link below:\n\n{link}\n\n"
            "If you did not create an account, please disregard this email.\n\n"
            "Best regards,\nReadMyBook Team"
        )
        msg["Subject"] = "Verification Code"
        msg["From"] = self.smtp_username
        msg["To"] = email_id
        with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
            server.starttls()
            server.login(self.smtp_username, self.smtp_password)
            server.send_message(msg)
            print("Verification email sent successfully")
    
    def send_verification_success_email(self, email_id):
        subject = "Verification Success"
        body = "Your email has been verified successfully. You can now login to your account."  
        msg = EmailMessage()
        msg.set_content(body)
        msg["Subject"] = subject
        msg["From"] = self.smtp_username
        msg["To"] = email_id
        with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
            server.starttls()
            server.login(self.smtp_username, self.smtp_password)
            server.send_message(msg)

    def send_password_reset_email(self, email_id: str, reset_code: str):
        msg = EmailMessage()

        msg.set_content(
            f"Dear User,\n\nWe received a request to reset your password. "
            f"Please use the following code to reset your password:\n\n{reset_code}\n\n"
            "If you did not request a password reset, please ignore this email.\n\n"
            "Best regards,\nReadMyBook Team"
        )
        msg["Subject"] = "Password Reset"
        msg["From"] = self.smtp_username
        msg["To"] = email_id
        with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
            server.starttls()
            server.login(self.smtp_username, self.smtp_password)
            server.send_message(msg)
            print("Password reset email sent successfully")

class UserService:

    def __init__(self, db: Session):
        self.user_repository = UserRepository(db)
        self.email_service = EmailService()

    def get_user_by_id(self, user_id: str):
        user = self.user_repository.get_user_by_id(user_id)
        if not user:
            return None

        user_response = GetUserResponse(
            user_id=user.user_id,
            first_name=user.first_name,
            last_name=user.last_name,
            date_of_birth=user.date_of_birth.isoformat(),
            gender=user.gender,
            email_id=user.email_id,
            created_at=user.created_at.isoformat(),
            updated_at=user.updated_at.isoformat(),
            deleted_at=user.deleted_at.isoformat() if user.deleted_at else "",
            is_deleted=user.is_deleted,
            is_active=user.is_active,
            is_verified=user.is_verified
        )
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
        return self.user_repository.update_user(user)

    def delete_user(self, user_id: str):
        deleted_user = self.user_repository.delete_user(user_id)
        if not deleted_user:
            raise HTTPException(status_code=404, detail="User not found")
        return deleted_user

    def create_user(self, signup_request: SignupRequest):

        verification_code = self.generate_verification_code()
        verification_code_expires_at = datetime.now() + timedelta(hours=1)
        dob = datetime.strptime(signup_request.date_of_birth, "%d-%m-%Y").date()
        user = User(
            email_id=signup_request.email_id,
            first_name=signup_request.first_name,
            last_name=signup_request.last_name,
            date_of_birth=dob,
            gender=signup_request.gender,
            verification_code=verification_code,
            verification_code_expires_at=verification_code_expires_at
        )
        user.user_id = "user_"+str(ulid.new())
        user.password = self.hash_password(signup_request.password)
        created_user = self.user_repository.create_user(user)
        self.send_verification_email(created_user)
        return created_user

    def login_user(self, login_request: LoginRequest):
        user = self.user_repository.get_user_by_email_id(login_request.email_id)
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        if not user.is_verified:
            raise HTTPException(status_code=401, detail="Email not verified")
        if not self.verify_password(login_request.password, user.password):
            raise HTTPException(status_code=401, detail="Invalid password")

        access_token, refresh_token = self.generate_tokens(user.user_id)
        
        return LoginResponse(access_token=access_token, refresh_token=refresh_token, user_id=user.user_id)
    
    def handle_google_oauth(self, google_user_info: dict):
        google_sub = google_user_info["sub"]
        email = google_user_info["email"]
        name = google_user_info.get("name", "")
        given_name = google_user_info.get("given_name", "")
        family_name = google_user_info.get("family_name", "")
        
        if not given_name and not family_name and name:
            name_parts = name.split(" ", 1)
            given_name = name_parts[0] if name_parts else ""
            family_name = name_parts[1] if len(name_parts) > 1 else ""
        
        user = self.user_repository.get_user_by_provider_id(google_sub, "google")
        
        if user:
            access_token, refresh_token = self.generate_tokens(user.user_id)
            return LoginResponse(
                access_token=access_token,
                refresh_token=refresh_token,
                user_id=user.user_id
            )
        
        user = self.user_repository.get_user_by_email_id(email)
        
        if user:
            raise HTTPException(
                status_code=409,
                detail=f"An account with this email already exists. Please use your original sign-in method."
            )
        
        user = User(
            email_id=email,
            first_name=given_name or "User",
            last_name=family_name,
            auth_provider="google",
            provider_id=google_sub,
            is_verified=True,
            password=None
        )
        user.user_id = "user_" + str(ulid.new())
        user.updated_at = datetime.now()
        
        created_user = self.user_repository.create_user(user)
        
        access_token, refresh_token = self.generate_tokens(created_user.user_id)
        
        return LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user_id=created_user.user_id
        )
        
    def generate_tokens(self, user_id: str):
        access_token = self.create_access_token(user_id)
        refresh_token = self.create_refresh_token(user_id)
        return access_token, refresh_token

    def hash_password(self, password: str) -> str:
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

    def send_verification_email(self, user: User):
        thread = threading.Thread(target=self.email_service.send_verification_email, args=(user.email_id, user.verification_code, user.user_id))
        thread.start()
        return thread
    
    def send_forget_password_email(self, email_id: str, reset_code: str):
        thread = threading.Thread(target=self.email_service.send_password_reset_email, args=(email_id, reset_code))
        thread.start()
        return thread

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
        updated_user = self.user_repository.update_user(user)
        self.email_service.send_verification_success_email(user.email_id)
        return True
    
    def forget_password(self, email_id: str):
        user = self.user_repository.get_user_by_email_id(email_id)
        if not user:
            return None
        reset_code = self.generate_verification_code()
        reset_code_expires_at = datetime.now() + timedelta(hours=1)
        user.pwd_reset_code = reset_code
        user.pwd_reset_code_expires_at = reset_code_expires_at
        user.updated_at = datetime.now()
        updated_user = self.user_repository.update_user(user)
        self.send_forget_password_email(email_id, reset_code)
        return True
    
    def reset_password(self, email_id: str, reset_code: str, new_password: str):
        user = self.user_repository.get_user_by_email_id(email_id)
        if not user:
            return None
        if user.pwd_reset_code != reset_code:
            return None
        if user.pwd_reset_code_expires_at < datetime.now():
            return None
        user.password = self.hash_password(new_password)
        user.pwd_reset_code = None
        user.pwd_reset_code_expires_at = None
        user.updated_at = datetime.now()
        updated_user = self.user_repository.update_user(user)
        return True


class GoogleAuthService:
    """Service for verifying Google ID tokens and extracting user information."""
    
    def __init__(self):
        from google.oauth2 import id_token
        from google.auth.transport import requests
        self.id_token = id_token
        self.requests = requests
        self.client_id = os.getenv("GOOGLE_WEB_CLIENT_ID")
        if not self.client_id:
            raise ValueError(
                "GOOGLE_WEB_CLIENT_ID environment variable is required. "
                "Please set it in your .env file."
            )
        self.request_session = requests.Request()
    
    def verify_id_token(self, id_token_string: str):
        try:
            id_info = self.id_token.verify_oauth2_token(
                id_token_string,
                self.request_session,
                self.client_id
            )
            
            if not id_info.get("email_verified", False):
                raise HTTPException(
                    status_code=403,
                    detail="Email address not verified by Google"
                )
            
            google_sub = id_info.get("sub")
            email = id_info.get("email")
            name = id_info.get("name", "")
            
            if not google_sub:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid token: missing 'sub' claim"
                )
            
            if not email:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid token: missing 'email' claim"
                )
            
            return {
                "sub": google_sub,
                "email": email,
                "name": name,
                "email_verified": id_info.get("email_verified", False),
                "picture": id_info.get("picture"),
                "given_name": id_info.get("given_name"),
                "family_name": id_info.get("family_name"),
            }
            
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(
                status_code=401,
                detail=f"Invalid Google ID token: {str(e)}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Error verifying Google ID token: {str(e)}"
            )
