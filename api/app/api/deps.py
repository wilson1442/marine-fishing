from typing import Generator
import hmac
import hashlib
import json
import base64
import time
import secrets
from datetime import datetime

import jwt as pyjwt
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


# ---------- API Key helpers ----------

def generate_api_key() -> tuple[str, str, str]:
    """Generate a new API key.
    Returns (full_key, key_hash, key_prefix) where:
    - full_key: mf_ + 32 hex chars (returned to user once)
    - key_hash: SHA-256 hash of full_key (stored in DB)
    - key_prefix: mf_ + first 8 chars (for display)
    """
    random_part = secrets.token_hex(16)  # 32 hex chars
    full_key = f"mf_{random_part}"
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()
    key_prefix = f"mf_{random_part[:8]}"
    return full_key, key_hash, key_prefix


def hash_api_key(key: str) -> str:
    """Hash an API key for comparison."""
    return hashlib.sha256(key.encode()).hexdigest()


def validate_api_key(db: Session, key: str) -> dict | None:
    """Validate an API key. Returns key info if valid, None otherwise."""
    if not key or not key.startswith("mf_"):
        return None

    key_hash = hash_api_key(key)

    row = db.execute(
        text("""
            SELECT id, key_prefix, label, is_active, expires_at, request_count
            FROM api_keys
            WHERE key_hash = :key_hash
        """),
        {"key_hash": key_hash}
    ).fetchone()

    if not row:
        return None

    if not row.is_active:
        return None

    if row.expires_at and row.expires_at < datetime.utcnow():
        return None

    # Update last_used_at and request_count
    db.execute(
        text("""
            UPDATE api_keys
            SET last_used_at = NOW(), request_count = request_count + 1
            WHERE id = :id
        """),
        {"id": row.id}
    )
    db.commit()

    return {
        "id": row.id,
        "key_prefix": row.key_prefix,
        "label": row.label,
        "auth_type": "api_key"
    }


def _verify_jwt_access_token(token: str) -> dict | None:
    """Verify a JWT access token. Returns payload or None."""
    settings = get_settings()
    try:
        payload = pyjwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != "access":
            return None
        return payload
    except (pyjwt.ExpiredSignatureError, pyjwt.InvalidTokenError):
        return None


def require_api_access(request: Request, db: Session = Depends(get_db)) -> dict:
    """
    FastAPI dependency: Allow access if any of:
    1. Valid X-API-Key header provided
    2. Valid Authorization: Bearer <jwt> header
    3. Valid user_token session cookie (logged-in user)
    4. Same-origin request (frontend) via Sec-Fetch-Site header
    """
    # Check 1: API Key header
    api_key = request.headers.get("X-API-Key")
    if api_key:
        key_info = validate_api_key(db, api_key)
        if key_info:
            return key_info
        raise HTTPException(status_code=401, detail="Invalid or expired API key")

    # Check 2: JWT Bearer token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        jwt_token = auth_header[7:]
        payload = _verify_jwt_access_token(jwt_token)
        if payload:
            user_id = int(payload["sub"])
            row = db.execute(
                text("SELECT id, email, status, expires_at FROM registered_users WHERE id = :id"),
                {"id": user_id}
            ).fetchone()
            if row and row.status == "approved":
                if not row.expires_at or row.expires_at >= datetime.utcnow():
                    return {
                        "user_id": row.id,
                        "username": row.email,
                        "auth_type": "jwt_bearer"
                    }
        raise HTTPException(status_code=401, detail="Invalid or expired Bearer token")

    # Check 3: Session cookie (logged-in user)
    token = request.cookies.get("user_token")
    if token:
        payload = _verify_token(token)
        if payload:
            # Verify user still exists and is approved
            row = db.execute(
                text("SELECT id, email, status, expires_at FROM registered_users WHERE id = :id"),
                {"id": payload["user_id"]}
            ).fetchone()
            if row and row.status == "approved":
                if not row.expires_at or row.expires_at >= datetime.utcnow():
                    return {
                        "user_id": row.id,
                        "username": row.email,
                        "auth_type": "session"
                    }

    # Check 4: Same-origin request (frontend)
    sec_fetch_site = request.headers.get("Sec-Fetch-Site")
    if sec_fetch_site == "same-origin":
        return {"auth_type": "same_origin"}

    # No valid authentication
    raise HTTPException(
        status_code=401,
        detail="Authentication required. Provide X-API-Key header, Bearer token, login, or access from the frontend."
    )


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
    """FastAPI dependency: read user_token cookie, verify token, confirm user has admin role."""
    token = request.cookies.get("user_token")
    payload = _verify_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    row = db.execute(
        text("SELECT id, email, first_name, last_name, role, status, expires_at FROM registered_users WHERE id = :id"),
        {"id": payload["user_id"]},
    ).fetchone()
    if not row or row.status != "approved" or row.role != "admin":
        raise HTTPException(status_code=401, detail="Not authenticated")
    if row.expires_at and row.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Account expired")
    return {
        "user_id": row.id,
        "username": row.email,
        "display_name": row.first_name + " " + row.last_name,
        "role": row.role,
    }
