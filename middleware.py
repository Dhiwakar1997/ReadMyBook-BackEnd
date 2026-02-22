from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from shared.redis import RedisService
from documents.data.repository import DocumentAccessRepository
from core.db_client import get_db
from sqlalchemy.orm import Session

import os
from billing.service.balance_service import BalanceService

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"


security = HTTPBearer()

def verify_access_token(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """
    Dependency to verify JWT access token from Authorization header.
    Returns the user_id from the token payload if valid.
    Raises HTTPException if token is invalid, expired, or missing.
    """
    token = credentials.credentials
    
    try:
        # Decode and verify the token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        # Extract user_id from the token
        user_id: str = payload.get("sub")
        token_type: str = payload.get("type")
        
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token: missing user_id",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Verify that this is an access token, not a refresh token
        if token_type != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type: access token required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        request.state.user_id = user_id
        return user_id
        
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Could not validate credentials: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
def document_access_validator(document_id: str, request: Request, db: Session = Depends(get_db), user_id=Depends(verify_access_token)):
    
    redis_service = RedisService()
    document_access = redis_service.get_value(f"doc:user:{user_id}")

    if document_access and document_id in document_access.keys():
        if document_access[document_id] not in ["owner", "shared"]:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Document access not found")
        else:
            request.state.accessible_documents = list(document_access.keys())
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
                return True
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Document access not found for this user")


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
