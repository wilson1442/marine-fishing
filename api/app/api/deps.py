from typing import Generator
import hmac
import hashlib
import json
import base64
import time

from fastapi import Request, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import SessionLocal
from app.config import get_settings


def get_db() -> Generator:
    """Dependency for getting database sessions"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------- Token helpers ----------

def _create_token(user_id: int, username: str) -> str:
    """Create an HMAC-signed token: base64url(payload).hex(signature)"""
    settings = get_settings()
    exp = time.time() + settings.admin_token_expiry_hours * 3600
    payload = json.dumps({"user_id": user_id, "username": username, "exp": exp})
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode()
    sig = hmac.new(
        settings.admin_secret_key.encode(),
        payload_b64.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload_b64}.{sig}"


def _verify_token(token: str) -> dict | None:
    """Verify HMAC signature and expiry. Returns payload dict or None."""
    if not token or "." not in token:
        return None
    parts = token.split(".", 1)
    if len(parts) != 2:
        return None
    payload_b64, sig = parts
    settings = get_settings()
    expected_sig = hmac.new(
        settings.admin_secret_key.encode(),
        payload_b64.encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:
        return None
    if payload.get("exp", 0) < time.time():
        return None
    return payload


def get_current_admin(request: Request, db: Session = Depends(get_db)):
    """FastAPI dependency: read cookie, verify token, confirm user is active."""
    token = request.cookies.get("admin_token")
    payload = _verify_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    row = db.execute(
        text("SELECT id, username, display_name, role, is_active FROM admin_users WHERE id = :id"),
        {"id": payload["user_id"]},
    ).fetchone()
    if not row or not row.is_active:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {
        "user_id": row.id,
        "username": row.username,
        "display_name": row.display_name,
        "role": row.role,
    }
