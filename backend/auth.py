"""
JWT + bcrypt authentication helpers for LeadFlow.
"""
import os
import logging
from datetime import datetime, timedelta
from typing import Optional

from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

logger = logging.getLogger(__name__)

SECRET_KEY = os.environ.get("JWT_SECRET", "leadflow-super-secret-key-2024-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 48

# Allow bridge calls without JWT using a static secret
BRIDGE_SECRET = os.environ.get("BRIDGE_SECRET", "leadflow-bridge-secret-2024")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
oauth2_optional = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_hours: int = ACCESS_TOKEN_EXPIRE_HOURS) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(hours=expires_hours)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """Dependency: require a valid JWT. Returns {username, user_id}."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_token(token)
    if not payload:
        raise credentials_exception
    username = payload.get("sub")
    user_id = payload.get("user_id")
    if not username or not user_id:
        raise credentials_exception
    return {"username": username, "user_id": int(user_id)}


async def get_current_user_optional(token: str = Depends(oauth2_optional)) -> Optional[dict]:
    """Dependency: optional JWT — returns user dict or None."""
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    username = payload.get("sub")
    user_id = payload.get("user_id")
    if not username or not user_id:
        return None
    return {"username": username, "user_id": int(user_id)}
