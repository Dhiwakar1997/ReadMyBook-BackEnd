from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from shared.redis import RedisService
from documents.data.repository import DocumentAccessRepository
from core.db_client import get_db
from sqlalchemy.orm import Session
from users.data.repository import UserRepository
from billing.data.repository import BalanceRepository

import os
from billing.service.balance_service import BalanceService

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"

# TTL for user context cache in Redis — 24 hours
USER_CONTEXT_CACHE_TTL = int(os.getenv("USER_CONTEXT_CACHE_TTL", str(60 * 60 * 24)))


def _user_context_key(user_id: str) -> str:
    return f"user:context:{user_id}"


security = HTTPBearer()

def verify_access_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> str:
    """
    Dependency to verify JWT access token from Authorization header.
    Returns the user_id from the token payload if valid.
    Also loads user_context (user profile + balance) into request.state,
    using Redis as a cache layer with DB fallback.
    """
    token = credentials.credentials

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        user_id: str = payload.get("sub")
        token_type: str = payload.get("type")

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token: missing user_id",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if token_type != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type: access token required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        request.state.user_id = user_id

        # ── Load user_context (Redis-first, DB fallback) ──────────────────
        redis = RedisService()
        user_context = redis.get_value(_user_context_key(user_id))

        if user_context is None:
            user = UserRepository(db).get_user_by_id(user_id)
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found",
                )

            balance = BalanceRepository(db).get_balance(user_id)

            user_context = {
                "user_id": user.user_id,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email_id": user.email_id,
                "is_private": user.is_private or False,
                "is_verified": user.is_verified or False,
                "bio": user.bio,
                "balance": balance,
            }
            try:
                redis.set_value(
                    _user_context_key(user_id),
                    user_context,
                    ttl=USER_CONTEXT_CACHE_TTL,
                )
            except Exception as e:
                print(f"[middleware] Failed to cache user_context for {user_id}: {e}")

        request.state.user_context = user_context
        return user_id

    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Could not validate credentials: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )

def user_verfication(user_id: str, request: Request, db: Session = Depends(get_db), auth_user_id=Depends(verify_access_token)):
    if user_id!=auth_user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Document owner access not found for this user")

def document_access_validator(document_id: str, request: Request, db: Session = Depends(get_db), user_id=Depends(verify_access_token)):
    
    redis_service = RedisService()
    document_access = redis_service.get_value(f"doc:user:{user_id}")

    if document_access and document_id in document_access.keys():
        if document_access[document_id] not in ["owner", "shared"]:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Document access not found")
        else:
            request.state.accessible_documents = list(document_access.keys())
            request.state.document_access = document_access
            return True

    db_document_access = DocumentAccessRepository(db)
    db_document_access = db_document_access.get_document_access_by_user_id(user_id)

    if db_document_access:
        document_access_dict = {}
        for document_access_item in db_document_access:
            document_access_dict[document_access_item.document_id] = "owner" if document_access_item.is_owner else "shared"
        redis_service.set_value(f"doc:user:{user_id}", document_access_dict, 60*60*24*5)

        if document_id in document_access_dict.keys():
            if document_access_dict[document_id] not in ["owner", "shared"]:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Document access not found for this user")
            else:
                request.state.accessible_documents = list(document_access_dict.keys())
                request.state.document_access= document_access_dict
                return True
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Document access not found for this user")

def owner_access_validator(document_id: str, request: Request, db: Session = Depends(get_db), user_id=Depends(document_access_validator)):
    document_access = request.state.document_access
    if document_access[document_id]!="owner":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Document owner access not found for this user")

def verify_balance(request: Request, user_id: str = Depends(verify_access_token)):
    """
    FastAPI dependency. Blocks paid endpoints when balance is empty.

    Read path:
      1. Redis GET billing:balance:{user_id}  → sub-millisecond
      2. If cache miss → PostgreSQL query → cache result in Redis
      3. If balance < MIN_BALANCE → 402 Payment Required

    This follows the same Redis-first pattern as document_access_validator.
    """
    svc = BalanceService()
    try:
        balance = svc.get_balance(user_id)
        if not svc.has_sufficient_balance(user_id):
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "insufficient_balance",
                    "message": "Your prepaid balance is empty. Please top up to continue.",
                    "balance": balance,
                },
            )
        request.state.balance = balance
    finally:
        svc.close()
