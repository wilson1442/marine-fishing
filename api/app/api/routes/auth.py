"""JWT authentication endpoints for mobile app."""

import hashlib
import secrets
import time
import re
import uuid
from datetime import datetime, timedelta
from typing import Optional

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.config import get_settings

router = APIRouter()


# ---------- Pydantic models ----------

class AuthLoginRequest(BaseModel):
    email: str
    password: str


class AuthRegisterRequest(BaseModel):
    first_name: str
    last_name: str
    email: str
    password: str


class AuthRefreshRequest(BaseModel):
    refresh_token: str


class AuthLogoutRequest(BaseModel):
    refresh_token: str


class AuthTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    user: dict


class UserInfo(BaseModel):
    id: int
    email: str
    first_name: str
    last_name: str
    role: str


# ---------- Rate limiter (in-memory, per IP) ----------

_login_attempts: dict[str, list[float]] = {}
_RATE_LIMIT_MAX = 5
_RATE_LIMIT_WINDOW = 300  # 5 minutes


def _check_rate_limit(request: Request, action: str = "login"):
    ip = request.client.host if request.client else "unknown"
    key = f"{action}:{ip}"
    now = time.time()
    attempts = _login_attempts.get(key, [])
    # Prune old attempts
    attempts = [t for t in attempts if now - t < _RATE_LIMIT_WINDOW]
    if len(attempts) >= _RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Please try again later."
        )
    attempts.append(now)
    _login_attempts[key] = attempts


# ---------- DB table ----------

def _ensure_refresh_tokens_table(db: Session):
    """Create the refresh_tokens table if it doesn't exist."""
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS refresh_tokens (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES registered_users(id) ON DELETE CASCADE,
            token_hash VARCHAR(128) NOT NULL UNIQUE,
            family_id VARCHAR(64) NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            revoked_at TIMESTAMP,
            replaced_by_id INTEGER REFERENCES refresh_tokens(id),
            user_agent TEXT,
            ip_address VARCHAR(45)
        )
    """))
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_refresh_tokens_token_hash ON refresh_tokens(token_hash)
    """))
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_refresh_tokens_family_id ON refresh_tokens(family_id)
    """))
    db.commit()


# ---------- Helpers ----------

def _hash_password(password: str, salt: str) -> str:
    """Hash password with SHA-256 + salt (same as admin.py)."""
    return hashlib.sha256((salt + password).encode()).hexdigest()


def _create_access_token(user_id: int, email: str, role: str) -> str:
    """Create a short-lived JWT access token."""
    settings = get_settings()
    now = datetime.utcnow()
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_token_expire_minutes),
    }
    return pyjwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _create_refresh_token(
    db: Session, user_id: int, request: Request, family_id: Optional[str] = None
) -> str:
    """Create an opaque refresh token and store its hash in DB."""
    settings = get_settings()
    raw_token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    if family_id is None:
        family_id = uuid.uuid4().hex

    expires_at = datetime.utcnow() + timedelta(days=settings.jwt_refresh_token_expire_days)
    user_agent = request.headers.get("User-Agent", "")[:500]
    ip_address = request.client.host if request.client else None

    db.execute(text("""
        INSERT INTO refresh_tokens (user_id, token_hash, family_id, expires_at, user_agent, ip_address)
        VALUES (:user_id, :token_hash, :family_id, :expires_at, :user_agent, :ip_address)
    """), {
        "user_id": user_id,
        "token_hash": token_hash,
        "family_id": family_id,
        "expires_at": expires_at,
        "user_agent": user_agent,
        "ip_address": ip_address,
    })
    db.commit()

    return raw_token


def _verify_access_token(token: str) -> dict | None:
    """Decode and verify a JWT access token. Returns payload or None."""
    settings = get_settings()
    try:
        payload = pyjwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != "access":
            return None
        return payload
    except pyjwt.ExpiredSignatureError:
        return None
    except pyjwt.InvalidTokenError:
        return None


def _validate_user_credentials(db: Session, email: str, password: str) -> dict | None:
    """Validate email + password. Returns user row dict or None."""
    row = db.execute(
        text("""
            SELECT id, email, first_name, last_name, password_hash, salt, status, expires_at, role
            FROM registered_users WHERE email = :email
        """),
        {"email": email.strip().lower()},
    ).fetchone()

    if not row:
        return None

    expected_hash = hashlib.sha256((row.salt + password).encode()).hexdigest()
    if expected_hash != row.password_hash:
        return None

    return {
        "id": row.id,
        "email": row.email,
        "first_name": row.first_name,
        "last_name": row.last_name,
        "status": row.status,
        "expires_at": row.expires_at,
        "role": row.role or "user",
    }


def _revoke_token_family(db: Session, family_id: str):
    """Revoke all non-revoked tokens in a family (theft detection)."""
    db.execute(text("""
        UPDATE refresh_tokens SET revoked_at = NOW()
        WHERE family_id = :family_id AND revoked_at IS NULL
    """), {"family_id": family_id})
    db.commit()


def _build_user_info(user: dict) -> dict:
    """Build the user info dict for token responses."""
    return {
        "id": user["id"],
        "email": user["email"],
        "first_name": user["first_name"],
        "last_name": user["last_name"],
        "role": user["role"],
    }


# ---------- Endpoints ----------

@router.post("/login")
def login(body: AuthLoginRequest, request: Request, db: Session = Depends(get_db)):
    """Authenticate with email/password, return access + refresh tokens."""
    _check_rate_limit(request, "login")
    _ensure_refresh_tokens_table(db)

    user = _validate_user_credentials(db, body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if user["status"] == "pending":
        raise HTTPException(status_code=403, detail="Your account is pending admin approval")
    if user["status"] == "denied":
        raise HTTPException(status_code=403, detail="Your account registration was denied")
    if user["status"] != "approved":
        raise HTTPException(status_code=403, detail="Account is not active")
    if user["expires_at"] and user["expires_at"] < datetime.utcnow():
        raise HTTPException(status_code=403, detail="Your account has expired. Please contact an administrator.")

    settings = get_settings()
    access_token = _create_access_token(user["id"], user["email"], user["role"])
    refresh_token = _create_refresh_token(db, user["id"], request)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": settings.jwt_access_token_expire_minutes * 60,
        "user": _build_user_info(user),
    }


@router.post("/register")
def register(body: AuthRegisterRequest, db: Session = Depends(get_db)):
    """Register a new user account (pending admin approval)."""
    # Validate email format
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', body.email):
        raise HTTPException(status_code=400, detail="Invalid email format")

    if not body.first_name.strip() or not body.last_name.strip():
        raise HTTPException(status_code=400, detail="First name and last name are required")
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    email = body.email.strip().lower()

    # Check duplicate
    existing = db.execute(
        text("SELECT id FROM registered_users WHERE email = :email"),
        {"email": email}
    ).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    salt = secrets.token_hex(32)
    password_hash = _hash_password(body.password, salt)

    result = db.execute(text("""
        INSERT INTO registered_users (first_name, last_name, email, password_hash, salt, status, role)
        VALUES (:first_name, :last_name, :email, :password_hash, :salt, 'pending', 'user')
        RETURNING id
    """), {
        "first_name": body.first_name.strip(),
        "last_name": body.last_name.strip(),
        "email": email,
        "password_hash": password_hash,
        "salt": salt,
    })
    db.commit()
    new_id = result.fetchone().id

    return {"id": new_id, "message": "Registration submitted. Awaiting admin approval."}


@router.post("/refresh")
def refresh(body: AuthRefreshRequest, request: Request, db: Session = Depends(get_db)):
    """Rotate refresh token, return new access + refresh token pair."""
    _ensure_refresh_tokens_table(db)

    token_hash = hashlib.sha256(body.refresh_token.encode()).hexdigest()

    # Look up the refresh token
    row = db.execute(text("""
        SELECT rt.id, rt.user_id, rt.family_id, rt.expires_at, rt.revoked_at,
               ru.email, ru.first_name, ru.last_name, ru.status, ru.expires_at as user_expires_at, ru.role
        FROM refresh_tokens rt
        JOIN registered_users ru ON rt.user_id = ru.id
        WHERE rt.token_hash = :token_hash
    """), {"token_hash": token_hash}).fetchone()

    if not row:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    # If this token was already revoked, it's a reuse — revoke entire family (theft detection)
    if row.revoked_at is not None:
        _revoke_token_family(db, row.family_id)
        raise HTTPException(status_code=401, detail="Refresh token reuse detected. All sessions revoked for security.")

    # Check expiry
    if row.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Refresh token expired")

    # Check user status
    if row.status != "approved":
        raise HTTPException(status_code=403, detail="Account is not active")
    if row.user_expires_at and row.user_expires_at < datetime.utcnow():
        raise HTTPException(status_code=403, detail="Account has expired")

    # Revoke the old token
    db.execute(text("""
        UPDATE refresh_tokens SET revoked_at = NOW() WHERE id = :id
    """), {"id": row.id})
    db.commit()

    # Issue new token pair in the same family
    settings = get_settings()
    user = {
        "id": row.user_id,
        "email": row.email,
        "first_name": row.first_name,
        "last_name": row.last_name,
        "role": row.role or "user",
    }

    access_token = _create_access_token(user["id"], user["email"], user["role"])
    new_refresh_token = _create_refresh_token(db, user["id"], request, family_id=row.family_id)

    # Link old token to the new one
    new_row = db.execute(text("""
        SELECT id FROM refresh_tokens WHERE token_hash = :hash
    """), {"hash": hashlib.sha256(new_refresh_token.encode()).hexdigest()}).fetchone()
    if new_row:
        db.execute(text("""
            UPDATE refresh_tokens SET replaced_by_id = :new_id WHERE id = :old_id
        """), {"new_id": new_row.id, "old_id": row.id})
        db.commit()

    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "token_type": "Bearer",
        "expires_in": settings.jwt_access_token_expire_minutes * 60,
        "user": _build_user_info(user),
    }


@router.post("/logout")
def logout(body: AuthLogoutRequest, db: Session = Depends(get_db)):
    """Revoke the refresh token's entire family."""
    _ensure_refresh_tokens_table(db)

    token_hash = hashlib.sha256(body.refresh_token.encode()).hexdigest()

    row = db.execute(text("""
        SELECT family_id FROM refresh_tokens WHERE token_hash = :token_hash
    """), {"token_hash": token_hash}).fetchone()

    if not row:
        # Don't reveal whether token existed
        return {"message": "Logged out"}

    _revoke_token_family(db, row.family_id)
    return {"message": "Logged out"}


@router.get("/me")
def get_me(request: Request, db: Session = Depends(get_db)):
    """Return current user info from the Bearer access token."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header required")

    token = auth_header[7:]
    payload = _verify_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired access token")

    user_id = int(payload["sub"])
    row = db.execute(
        text("SELECT id, email, first_name, last_name, status, expires_at, role FROM registered_users WHERE id = :id"),
        {"id": user_id},
    ).fetchone()

    if not row or row.status != "approved":
        raise HTTPException(status_code=401, detail="Account not active")
    if row.expires_at and row.expires_at < datetime.utcnow():
        raise HTTPException(status_code=403, detail="Account expired")

    return {
        "id": row.id,
        "email": row.email,
        "first_name": row.first_name,
        "last_name": row.last_name,
        "role": row.role or "user",
    }
