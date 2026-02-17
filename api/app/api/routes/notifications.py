"""Push notification device token registration for mobile apps."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_api_access

router = APIRouter()


class RegisterDeviceRequest(BaseModel):
    token: str
    platform: str
    device_id: str | None = None

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        v = v.lower()
        if v not in ("ios", "android"):
            raise ValueError("platform must be 'ios' or 'android'")
        return v

    @field_validator("token")
    @classmethod
    def validate_token(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 512:
            raise ValueError("token must be 1-512 characters")
        return v


class UnregisterDeviceRequest(BaseModel):
    token: str


def _ensure_push_tokens_table(db: Session):
    """Create the push_tokens table if it doesn't exist."""
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS push_tokens (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES registered_users(id) ON DELETE CASCADE,
            token VARCHAR(512) NOT NULL,
            platform VARCHAR(10) NOT NULL CHECK (platform IN ('ios', 'android')),
            device_id VARCHAR(128),
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(user_id, token)
        )
    """))
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_push_tokens_user_id ON push_tokens(user_id)
    """))
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_push_tokens_active ON push_tokens(is_active) WHERE is_active = true
    """))
    db.commit()


def _get_user_id(auth: dict) -> int:
    user_id = auth.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="User authentication required")
    return user_id


@router.post("/register-device")
def register_device(
    body: RegisterDeviceRequest,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_api_access),
):
    """Register or re-activate a push notification token for the current user."""
    user_id = _get_user_id(auth)
    _ensure_push_tokens_table(db)

    db.execute(
        text("""
            INSERT INTO push_tokens (user_id, token, platform, device_id, is_active, updated_at)
            VALUES (:uid, :token, :platform, :device_id, TRUE, NOW())
            ON CONFLICT (user_id, token) DO UPDATE
                SET is_active = TRUE,
                    platform = :platform,
                    device_id = :device_id,
                    updated_at = NOW()
        """),
        {
            "uid": user_id,
            "token": body.token,
            "platform": body.platform,
            "device_id": body.device_id,
        },
    )
    db.commit()

    return {"status": "registered", "token": body.token, "platform": body.platform}


@router.delete("/unregister-device")
def unregister_device(
    body: UnregisterDeviceRequest,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_api_access),
):
    """Mark a push token as inactive for the current user."""
    user_id = _get_user_id(auth)
    _ensure_push_tokens_table(db)

    result = db.execute(
        text("""
            UPDATE push_tokens
            SET is_active = FALSE, updated_at = NOW()
            WHERE user_id = :uid AND token = :token
        """),
        {"uid": user_id, "token": body.token.strip()},
    )
    db.commit()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Token not found")

    return {"status": "unregistered", "token": body.token}
