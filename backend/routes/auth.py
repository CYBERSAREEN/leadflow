import logging
from fastapi import APIRouter, HTTPException, Depends
from backend import database, auth
from backend.models import LoginRequest, TokenResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginRequest):
    """Authenticate user and return JWT token."""
    try:
        user = database.get_user_by_username(body.username.strip().lower())
        if not user:
            raise HTTPException(status_code=401, detail="Invalid username or password")

        if not auth.verify_password(body.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid username or password")

        token = auth.create_access_token({
            "sub": user["username"],
            "user_id": user["id"],
        })

        return {
            "access_token": token,
            "token_type": "bearer",
            "username": user["username"],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POST /auth/login error: {e}")
        raise HTTPException(status_code=500, detail="Login failed")


@router.get("/auth/me")
async def get_me(current_user: dict = Depends(auth.get_current_user)):
    """Get current authenticated user info."""
    return current_user


@router.post("/auth/change-password")
async def change_password(body: dict, current_user: dict = Depends(auth.get_current_user)):
    """Change password for the current user."""
    try:
        old_password = body.get("old_password", "")
        new_password = body.get("new_password", "")

        if not old_password or not new_password:
            raise HTTPException(status_code=400, detail="old_password and new_password required")

        if len(new_password) < 8:
            raise HTTPException(status_code=400, detail="New password must be at least 8 characters")

        user = database.get_user_by_username(current_user["username"])
        if not user or not auth.verify_password(old_password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Old password is incorrect")

        new_hash = auth.get_password_hash(new_password)
        try:
            sb = database._get_client()
            sb.table("users").update({"password_hash": new_hash}).eq("id", current_user["user_id"]).execute()
        except Exception as e:
            raise HTTPException(status_code=500, detail="Failed to update password")

        return {"message": "Password changed successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POST /auth/change-password error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
